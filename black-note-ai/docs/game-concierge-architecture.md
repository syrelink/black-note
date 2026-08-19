# GameRover：可控单 Agent Harness

GameRover 当前定位为一个面向中文玩家的游戏资讯与玩法助手。它暂时不使用多 Agent，而是先实现一个完整、可控、可持续多轮对话的单 Agent Harness。

## 运行流程

```text
用户输入
  → TurnContext
  → ContextCompaction（测压；多数时候 no-op）
  → Agent
      ├─ 直接回答 → END
      └─ Tool Calling → ToolExecution → ContextCompaction → Agent
```

核心文件：

- `graph.py`：Agent Loop、Tool Runtime、停止条件。
- `memory.py`：上下文预算、安全切分和滚动摘要。
- `models.py`：Harness State、ContextSummary、Token Ledger、Tool Trace。
- `tools.py`：游戏资料/Wiki/攻略与实时资讯搜索。
- `skills/`：Agent Skills 元数据、工作流、references 与安全加载器。
- `attachments.py`：附件引用协议、图片临时 Hydration 与文档文本提取能力。

`TurnContext` 是每个用户 Turn 的初始化节点。LangGraph Checkpointer 会跨轮保留会话状态，因此这里会清空上一轮的 `tool_trace`、`skill_trace`、Token Usage 和工具轮次计数，递增 `turn_count`，并把新到达的 HumanMessage 同步进 Token 估算缓存。它不负责生成摘要，也不负责选择模型上下文。

## 模型上下文

每次调用模型前，Harness 动态组装：

```text
System Prompt
+ ContextSummary
+ Recent Messages
+ Current Turn / Tool Results（包括按需加载的 Skill 正文）
```

PostgreSQL Checkpoint 保存线程状态，但模型不会直接看到所有历史 Checkpoint。模型可见内容由 `ContextManager` 按预算选择。聊天页面在 PostgreSQL 中另存一份不可变 Transcript，因此模型上下文被自动压缩后，用户仍能在左侧历史会话中查看完整聊天记录。

## 多模态输入与压缩

点击输入框左侧加号后，浏览器以 Data URL 上传图片。服务端立即解码并写入 MinIO，PostgreSQL 只保存 `attachment_id`、会话归属、MIME、大小和 `object_key`，LangGraph State 也只保存引用。`Agent` 节点调用模型前才根据 `object_key` 从 MinIO 读取当前 Turn 的图片，临时组装多模态 `model_context`；这个含 Base64 的临时副本不会写回 State。

```text
选择本地文件
→ 浏览器预览并编码 Data URL
→ ChatRequest 校验（最多 5 个、单个 10MB、合计 20MB）
→ 图片 bytes 写入 MinIO，PostgreSQL 写入 attachment_id + object_key
→ HumanMessage 只写 attachment://{id}
→ Agent 调用前按 id 临时 Hydrate 原图
→ 主模型联合理解文字与图片
→ 回答和有界图片分析记录写回 State，原图不写回
```

当前阶段只接收图片附件。MinIO bucket 保存原图，PostgreSQL `chat_attachments` 只保存元数据与 `object_key`，Transcript 保存带会话归属的附件 URL，LangGraph Checkpoint 只保存 `AttachmentRef`。下一轮默认不重新 Hydrate 旧图；删除会话时同步删除其 MinIO 对象。启动迁移会删除没有 MinIO `object_key` 的旧附件记录，并移除旧版 `content BYTEA` 列，系统不再提供数据库二进制回退路径。

## 滚动摘要

默认预算可通过环境变量调整：

```text
GAME_EFFECTIVE_CONTEXT_TOKENS=65536
GAME_CONTEXT_TRIGGER_RATIO=0.8
GAME_CONTEXT_RETAIN_RATIO=0.16
GAME_SUMMARY_BUDGET_TOKENS=8192
GAME_COMPACTION_RETRIES=1
GAME_TOOL_PRUNE_THRESHOLD_TOKENS=1800
GAME_TOOL_PRUNE_RETAIN_TOKENS=600
GAME_TOOL_RESULT_BUDGET_TOKENS=2500
```

默认在有效窗口达到 80% 时触发压缩，并逐字保留窗口 16% 的近期消息。Token Ledger 在这里仅是当前 LangGraph State 的增量估算缓存，不是事件源，也不通过 Replay 重建上下文。真正运行时上下文始终由 `state.messages + ContextSummary` 组装。

事件日志只用于观测与评测：每次模型调用前记录 `context/pressure`，模型结束记录 `estimated_input_tokens` 与供应商返回的 `provider_input_tokens`。两者可以计算估算误差、验证压缩触发时机，但日志不会反过来驱动 Agent。这个取舍让小型 Harness 保持单一事实源，也避免实现一套不必要的 Event Sourcing 系统。

每次模型请求前都会检查压力。触发压缩后先裁剪较早的大型 Tool Result；重新测量后仍超过触发线，才执行结构化摘要：

```text
New ContextSummary
= Compress(Old ContextSummary + Newly Expired Complete Turns)
```

摘要不会 append。每次都生成一份新的当前有效状态，并受固定 Summary Budget 限制。

Recent 区按 Token 从后向前选择完整用户轮次。一个用户轮次包含该用户消息之后的所有 Assistant Tool Call、Tool Result 和最终回答，因此 Tool Call 与 Tool Result 不会被切断。单个 Turn 自身超大时，系统退化为按闭合工具单元切分，并继续保证 Tool Call 与 Tool Result 成对处理。压缩后会重新测量；低于触发线且确实缩小才视为收敛。

## 持久会话

LangGraph 使用官方 `AsyncPostgresSaver`。同一个 PostgreSQL 实例同时保存：

```text
LangGraph checkpoints / checkpoint_blobs / checkpoint_writes
chat_sessions
chat_transcript
agent_runs
agent_run_events
```

相同 `session_id` 在服务和容器重启后仍能恢复，数据由 Docker named volume 持久化。

`agent_runs` 保存每轮执行的耗时、Token、压缩状态和工具数量；`agent_run_events` 按顺序保存节点、实际经过的边、Tool Calling 参数与结果摘要。右侧面板将当前 Turn 置顶并自动展开，历史 Turn 默认折叠，最多读取最近 20 轮。

## Tool Runtime

模型可见工具保持为三个：

- `skill(name)`：返回完整 `SKILL.md`，作为 ToolMessage 供下一次 Agent Step 使用。
- `read_skill_reference(name, path)`：安全读取 Skill 明确引用且当前任务需要的 `references/*.md`。
- `web_search(query, depth)`：模型自主决定是否调用，并通过 `quick` 或 `research` 选择快速查询或多来源研究；Query 可以来自文字、图片理解和对话上下文。

## Agent Skills 与渐进式披露

进程启动并构建 Agent 时，`SkillRegistry` 的构造函数会调用 `refresh()`，通过 `root.glob("*/SKILL.md")` 自动扫描 Skill，解析 YAML Frontmatter 并校验目录名、`name` 和 `description`。随后 `catalog_prompt()` 只把 `name + description` 目录拼进 System Prompt。完整正文不会常驻；模型判断任务需要专业流程时调用 `skill(name)`，正文才作为 ToolMessage 进入下一步。只有正文明确要求且当前任务需要时，模型才调用 `read_skill_reference`。

扫描不是每次请求执行，也不是文件热更新。服务运行期间新增 Skill 后，需要重启 Agent 或显式调用 `refresh()` 并重新构建 System Prompt。

```text
元数据目录（始终加载）
→ SKILL.md（Skill 激活后加载）
→ references/*.md（当前分支需要时加载）
```

当前包含：

- `gameplay-guide`：任务路线、Boss、地图、解谜和当前画面下一步指导。
- `game-build-advisor`：基于账号、装备、属性和资源的配队与养成建议。
- `game-news`：最新公告、版本动态、行业新闻和传闻核验。

Skill 不是 LangGraph 节点，而是 Registry 提供的模型工具。这样所有 Skill 都复用同一条 `Agent → ToolExecution → Agent` 循环，新增 Skill 只增加文档，不增加节点和边。`ToolExecution` 在一个节点内完成工具执行、ToolMessage 写回、轨迹提取和 Skill 审计；`HarnessState.skill_trace` 只记录本轮加载情况，正文作为标准 ToolMessage 保留。

寒暄、情绪陪伴、创作改写、主观建议，以及当前对话或附件已经足够回答的问题不会触发搜索。简单、明确、单事实问题走快速搜索；配队、机制、攻略、比较和多来源核验走 Agentic Search。

`web_search` 内部使用统一 Search Harness：

```text
动态 Query 规划 → DuckDuckGo 并行搜索
→ URL/标题跨轮去重 → 按需打开新网页 → 页内相关段落提取
→ 来源分类与证据重排 → 证据充分性检查
→ 证据不足时根据缺口生成下一轮 Query
```

DuckDuckGo 是当前零 API Key 的默认 `SearchBackend`。具体实现位于 `search/duckduckgo.py`，业务编排位于 `search/service.py`，后续可增加其他正式搜索 API 而无需修改 Agent Tool 契约。

Tool Runtime 负责：

- 参数化调用；
- 并发执行一轮中的多个工具；
- 超时控制；
- 异常标准化；
- 大结果截断；
- 记录参数、状态、耗时和结果预览。
- 提取 Search Harness 的 `pipeline`，在右侧展开显示每个检索阶段。

搜索工具返回两个语义 Output Item：

```text
web_search_call
  └─ mode / status / search | open_page | find_in_page actions

search_message
  └─ evidence / sufficient / missing_information
```

`SearchReport` 仍是 Search Harness 内部聚合对象，但暴露给 Agent 时通过 `tool_payload()` 转换为上述两个 Output Item。执行轨迹读取 `web_search_call`，最终回答只使用 `search_message.evidence`；详细 Pipeline 独立放在 Trace 中，避免执行元数据挤占模型的证据预算。

## 实时执行可视化

前端通过 `POST /ai/chat/stream` 建立 SSE 流。Harness 每完成一个 LangGraph 节点就发送一次事件，右侧面板实时展示节点、实际经过的边、累计耗时、Tool Calling 参数和结果预览。最终回答单独作为 `final` 事件返回，并在浏览器中进行安全 Markdown 渲染。

可观测协议按 `Turn → Step → Event` 组织：一次用户请求是一个 Turn；一次模型请求及其触发的工具批次是一个 Step。持久事件包括 `turn/start`、`step/start`、`model/start`、`model/first_token`、`model/end`、`tool/call`、`tool/result`、压缩生命周期、`step/end` 与 `turn/end`。模型事件记录 TTFT、生成耗时、输入输出 Token 和生成速度；工具事件记录执行、后处理、超时与错误类型；压缩事件记录压缩前后 Token、消息边界与收敛状态。

高频的模型文本分片只通过 SSE 发送，不写入事件表；可恢复的语义事件按顺序写入 PostgreSQL。`SessionStore` 使用连接池复用数据库连接，避免日志写入本身放大响应延迟。`GET /ai/sessions/{session_id}/runs` 可在刷新或切换会话后恢复每轮轨迹，即使运行失败，已经发生的事件也不会丢失。

日志评测关注四组可直接计算的指标：

- 上下文：压力超过阈值时是否触发压缩、压缩后 Token 降幅、是否收敛。
- Token 估算：`abs(estimated - provider) / provider`，只评估误差，不校正历史消息。
- Skill：应触发样本的召回率、不应触发样本的误触发率、reference 是否按需加载。
- 性能与可靠性：TTFT、总耗时、工具超时率、工具成功率和达到轮次上限的比例。

## 启动

```bash
docker compose up -d postgres
conda activate black
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

打开 `http://127.0.0.1:8001/`。左侧展示持久化历史会话，中间是聊天区，右侧展示 Tool Trace、上下文预算、ContextSummary 和自动压缩状态。

调试接口：

- `GET /ai/sessions`：列出历史会话。
- `GET /ai/sessions/{session_id}/messages`：读取完整展示 Transcript。
- `GET /ai/sessions/{session_id}/runs`：读取最近的逐轮 Harness 执行轨迹。
- `GET /ai/sessions/{session_id}/state`：检查完整 LangGraph State。
