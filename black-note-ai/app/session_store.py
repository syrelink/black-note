from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.game_agent.attachments import decode_data_url


class SessionStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )

    async def _connect(self):
        """从连接池借用连接，避免每条 Harness 事件重新建立 TCP 连接。"""
        return self.pool.connection()

    async def setup(self) -> None:
        await self.pool.open()
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                        session_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_transcript (
                        id BIGSERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                        content TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                await cursor.execute(
                    "ALTER TABLE chat_transcript ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb"
                )
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_attachments (
                        attachment_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        mime_type TEXT NOT NULL,
                        size INTEGER NOT NULL,
                        content BYTEA NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                await cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_chat_attachments_session ON chat_attachments(session_id, created_at)"
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chat_transcript_session
                    ON chat_transcript(session_id, id)
                    """
                )
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_runs (
                        run_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                        turn_number INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        started_at TIMESTAMPTZ NOT NULL,
                        completed_at TIMESTAMPTZ NOT NULL,
                        elapsed_ms INTEGER NOT NULL,
                        compacted BOOLEAN NOT NULL DEFAULT FALSE,
                        context_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
                        tool_call_count INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(session_id, turn_number)
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_run_events (
                        id BIGSERIAL PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
                        sequence INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        node TEXT,
                        step_number INTEGER,
                        component TEXT,
                        status TEXT,
                        duration_ms INTEGER,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        payload JSONB NOT NULL,
                        UNIQUE(run_id, sequence)
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_agent_runs_session
                    ON agent_runs(session_id, turn_number DESC)
                    """
                )
                await cursor.execute(
                    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS error_type TEXT"
                )
                await cursor.execute(
                    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS error_message TEXT"
                )
                await cursor.execute(
                    "ALTER TABLE agent_run_events ADD COLUMN IF NOT EXISTS step_number INTEGER"
                )
                await cursor.execute(
                    "ALTER TABLE agent_run_events ADD COLUMN IF NOT EXISTS component TEXT"
                )
                await cursor.execute(
                    "ALTER TABLE agent_run_events ADD COLUMN IF NOT EXISTS status TEXT"
                )
                await cursor.execute(
                    "ALTER TABLE agent_run_events ADD COLUMN IF NOT EXISTS duration_ms INTEGER"
                )
                await cursor.execute(
                    "ALTER TABLE agent_run_events ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
                )
                await cursor.execute(
                    "ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_session_id_turn_number_key"
                )
                await cursor.execute(
                    """
                    UPDATE agent_runs
                    SET status = 'interrupted', completed_at = NOW()
                    WHERE status = 'running'
                    """
                )

    async def close(self) -> None:
        await self.pool.close()

    async def record_user_message(
        self,
        session_id: str,
        question: str,
        attachments: list | None = None,
    ) -> list[dict]:
        """请求一到达就保存用户消息和图片，保证刷新或模型失败后仍可恢复。"""
        now = datetime.now().astimezone()
        stored_attachments = []
        for attachment in attachments or []:
            item = attachment.model_dump() if hasattr(attachment, "model_dump") else dict(attachment)
            raw = decode_data_url(item["data_url"], item["size"])
            attachment_id = str(uuid4())
            stored_attachments.append({
                "attachment_id": attachment_id,
                "name": item["name"],
                "mime_type": item["mime_type"],
                "size": item["size"],
                "data_url": f"/ai/attachments/{attachment_id}",
                "content": raw,
            })
        transcript_attachments = [
            {key: value for key, value in item.items() if key != "content"}
            for item in stored_attachments
        ]
        async with await self._connect() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO chat_sessions(session_id, title, created_at, updated_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT(session_id) DO UPDATE SET updated_at = EXCLUDED.updated_at
                        """,
                        (session_id, self._title(question), now, now),
                    )
                    if stored_attachments:
                        await cursor.executemany(
                            """
                            INSERT INTO chat_attachments(
                                attachment_id, session_id, name, mime_type, size, content, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            [
                                (
                                    item["attachment_id"], session_id, item["name"], item["mime_type"],
                                    item["size"], item["content"], now,
                                )
                                for item in stored_attachments
                            ],
                        )
                    await cursor.execute(
                        """
                        INSERT INTO chat_transcript(session_id, role, content, created_at, attachments)
                        VALUES (%s, 'user', %s, %s, %s::jsonb)
                        """,
                        (session_id, question, now, json.dumps(transcript_attachments, ensure_ascii=False)),
                    )
        return transcript_attachments

    async def record_assistant_message(self, session_id: str, answer: str) -> None:
        now = datetime.now().astimezone()
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO chat_transcript(session_id, role, content, created_at, attachments)
                    VALUES (%s, 'assistant', %s, %s, '[]'::jsonb)
                    """,
                    (session_id, answer, now),
                )
                await cursor.execute(
                    "UPDATE chat_sessions SET updated_at = %s WHERE session_id = %s",
                    (now, session_id),
                )

    async def get_attachment(self, attachment_id: str) -> dict | None:
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT name, mime_type, content FROM chat_attachments WHERE attachment_id = %s",
                    (attachment_id,),
                )
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def list_sessions(self) -> list[dict]:
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT session_id, title, updated_at
                    FROM chat_sessions
                    ORDER BY updated_at DESC
                    """
                )
                return [dict(row) for row in await cursor.fetchall()]

    async def get_messages(self, session_id: str) -> list[dict]:
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT role, content, created_at, attachments
                    FROM chat_transcript
                    WHERE session_id = %s
                    ORDER BY id
                    """,
                    (session_id,),
                )
                return [dict(row) for row in await cursor.fetchall()]

    async def rename_session(self, session_id: str, title: str) -> bool:
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "UPDATE chat_sessions SET title = %s WHERE session_id = %s RETURNING session_id",
                    (title, session_id),
                )
                return await cursor.fetchone() is not None

    async def delete_session(self, session_id: str) -> bool:
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "DELETE FROM chat_sessions WHERE session_id = %s RETURNING session_id",
                    (session_id,),
                )
                return await cursor.fetchone() is not None

    async def record_run(
        self,
        *,
        run_id: str,
        session_id: str,
        turn_number: int,
        started_at: datetime,
        elapsed_ms: int,
        compacted: bool,
        context_metrics: dict,
        tool_call_count: int,
        events: list[dict],
    ) -> None:
        completed_at = datetime.now().astimezone()
        async with await self._connect() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO agent_runs(
                            run_id, session_id, turn_number, status, started_at, completed_at,
                            elapsed_ms, compacted, context_metrics, tool_call_count
                        ) VALUES (%s, %s, %s, 'completed', %s, %s, %s, %s, %s::jsonb, %s)
                        ON CONFLICT(run_id) DO NOTHING
                        """,
                        (
                            run_id, session_id, turn_number, started_at, completed_at,
                            elapsed_ms, compacted, json.dumps(context_metrics), tool_call_count,
                        ),
                    )
                    if events:
                        await cursor.executemany(
                            """
                            INSERT INTO agent_run_events(
                                run_id, sequence, event_type, node, step_number,
                                component, status, duration_ms, payload
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                            ON CONFLICT(run_id, sequence) DO NOTHING
                            """,
                            [
                                (
                                    run_id,
                                    sequence,
                                    event.get("event_type", "node"),
                                    event.get("node"),
                                    event.get("step_number"),
                                    event.get("component"),
                                    event.get("status"),
                                    event.get("duration_ms"),
                                    json.dumps(event, ensure_ascii=False, default=str),
                                )
                                for sequence, event in enumerate(events, start=1)
                            ],
                        )

    async def start_run(
        self,
        *,
        run_id: str,
        session_id: str,
        turn_number: int,
        started_at: datetime,
    ) -> None:
        """请求开始即建立运行记录，避免异常时整轮轨迹消失。"""
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO agent_runs(
                        run_id, session_id, turn_number, status, started_at, completed_at,
                        elapsed_ms, compacted, context_metrics, tool_call_count
                    ) VALUES (%s, %s, %s, 'running', %s, %s, 0, FALSE, '{}'::jsonb, 0)
                    ON CONFLICT(run_id) DO NOTHING
                    """,
                    (run_id, session_id, turn_number, started_at, started_at),
                )

    async def append_run_event(
        self,
        *,
        run_id: str,
        sequence: int,
        event: dict,
    ) -> None:
        """将语义事件按发生顺序立即追加到 PostgreSQL。"""
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO agent_run_events(
                        run_id, sequence, event_type, node, step_number,
                        component, status, duration_ms, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT(run_id, sequence) DO NOTHING
                    """,
                    (
                        run_id,
                        sequence,
                        event.get("event_type", "event"),
                        event.get("node"),
                        event.get("step_number"),
                        event.get("component"),
                        event.get("status"),
                        event.get("duration_ms"),
                        json.dumps(event, ensure_ascii=False, default=str),
                    ),
                )

    async def finish_run(
        self,
        *,
        run_id: str,
        status: str,
        elapsed_ms: int,
        compacted: bool = False,
        context_metrics: dict | None = None,
        tool_call_count: int = 0,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """闭合成功或失败的 Run；已追加事件不会因失败而丢失。"""
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE agent_runs
                    SET status = %s,
                        completed_at = %s,
                        elapsed_ms = %s,
                        compacted = %s,
                        context_metrics = %s::jsonb,
                        tool_call_count = %s,
                        error_type = %s,
                        error_message = %s
                    WHERE run_id = %s
                    """,
                    (
                        status,
                        datetime.now().astimezone(),
                        elapsed_ms,
                        compacted,
                        json.dumps(context_metrics or {}, ensure_ascii=False),
                        tool_call_count,
                        error_type,
                        error_message,
                        run_id,
                    ),
                )

    async def list_runs(self, session_id: str, limit: int = 20) -> list[dict]:
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT run_id, turn_number, status, started_at, completed_at, elapsed_ms,
                           compacted, context_metrics, tool_call_count, error_type, error_message
                    FROM agent_runs
                    WHERE session_id = %s
                    ORDER BY turn_number DESC
                    LIMIT %s
                    """,
                    (session_id, limit),
                )
                runs = [dict(row) for row in await cursor.fetchall()]
                if not runs:
                    return []
                run_ids = [run["run_id"] for run in runs]
                await cursor.execute(
                    """
                    SELECT run_id, sequence, payload
                    FROM agent_run_events
                    WHERE run_id = ANY(%s)
                    ORDER BY run_id, sequence
                    """,
                    (run_ids,),
                )
                events_by_run = {run_id: [] for run_id in run_ids}
                for row in await cursor.fetchall():
                    events_by_run[row["run_id"]].append(row["payload"])
                for run in runs:
                    run["events"] = events_by_run[run["run_id"]]
                return runs

    @staticmethod
    def _title(question: str) -> str:
        normalized = " ".join(question.split())
        return normalized[:28] + ("…" if len(normalized) > 28 else "")
