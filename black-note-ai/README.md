# black-note-ai（AI 笔记助手微服务）

这是 **AI 微服务**，负责向量库（ChromaDB）、RAG 问答、Agent 能力，并对外提供 FastAPI 接口。
整体调用链路：**前端 → SpringBoot（鉴权/业务）→ FastAPI（AI）**

---

## 目录结构

```text
black-note-ai/
├── app/                      # 全部业务代码（只看这里）
│   ├── main.py               # FastAPI 入口 + 所有路由
│   ├── schemas.py            # 请求体 Pydantic 模型
│   ├── auth.py               # 获取 user_id（X-User-Id / Authorization兜底）
│   ├── rag.py                # RAG Chain：改写问题→检索→生成（带多轮历史）
│   ├── agent.py              # Agent：工具（搜索/读笔记）+ LLM
│   └── store/
│       ├── embeddings.py     # 本地 embedding（bge-m3 单例）
│       ├── vectorstore.py    # ChromaDB + MySQL 增量同步（sync/delete）
│       └── redis_client.py   # token → userId（复用 SpringBoot Redis）
├── scripts/
│   └── build_index.py        # 一次性全量建库（清空旧collection后重建）
├── chroma_db/                # 向量数据库文件（自动生成，勿手动修改）
├── .env                      # 环境变量
├── requirements.txt
└── README.md
```

---

## 环境准备

- **MySQL**：与 SpringBoot 使用同一个 `black_note` 库
- **Redis**：与 SpringBoot 使用同一个实例（仅用于直连 FastAPI 时的 token 兜底）
- **Python**：3.10+

安装依赖：

```bash
pip install -r requirements.txt
```

`.env` 配置：

```bash
# LLM（DeepSeek 兼容 OpenAI API）
DEEPSEEK_API_KEY=xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# 向量库
CHROMA_DIR=./chroma_db
CHROMA_COLLECTION=black_note_all

# MySQL（给 sync/delete 接口用）
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=123456
MYSQL_DB=black_note

# Redis（仅用于 Authorization 兜底）
REDIS_URL=redis://127.0.0.1:6379/0
```

---

## 快速启动

### 第一步：全量建库（首次必须执行）

```bash
python scripts/build_index.py
```

从 MySQL 读取所有 `is_deleted=0` 的笔记，清空旧 collection 后重新向量化写入 `chroma_db/`。

### 第二步：启动 FastAPI

```bash
uvicorn app.main:app --port 8001 --reload
```

健康检查：

```bash
curl -s http://127.0.0.1:8001/ai/health
```

---

## 接口说明

> 推荐由 SpringBoot 调用并带 `X-User-Id`（内部信任），前端只调 SpringBoot。

| 方法 | 路径 | 用途 | 鉴权 |
|---|---|---|---|
| POST | `/ai/chat` | RAG 多轮问答（SSE 流式） | `X-User-Id` 或 `Authorization` |
| GET | `/ai/search` | 语义搜索笔记列表 | 同上 |
| POST | `/ai/agent` | Agent 任务（SSE 流式） | body 传 `user_id` |
| POST | `/ai/sync_note` | 增量同步一条笔记到向量库 | 内部调用（SpringBoot 发布笔记后） |
| POST | `/ai/delete_note` | 从向量库删除一条笔记 | 内部调用（SpringBoot 删除笔记后） |
| GET | `/ai/health` | 健康检查 | 无 |

---

## curl 示例

```bash
# RAG 问答（SSE）
curl -N -X POST "http://127.0.0.1:8001/ai/chat" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: 6" \
  -d '{"question":"我最近写过哪些关于Redis的笔记？","session_id":"demo"}'

# 语义搜索
curl -s "http://127.0.0.1:8001/ai/search?q=Redis" -H "X-User-Id: 6"

# 增量同步（发布笔记后调用）
curl -s -X POST "http://127.0.0.1:8001/ai/sync_note" \
  -H "Content-Type: application/json" -d '{"note_id": 123}'

# 删除同步（删除笔记后调用）
curl -s -X POST "http://127.0.0.1:8001/ai/delete_note" \
  -H "Content-Type: application/json" -d '{"note_id": 123}'
```
