# GameRover：可控单 Agent Harness

GameRover 当前定位为一个面向中文玩家的游戏资讯与玩法助手。它暂时不使用多 Agent，而是先实现一个完整、可控、可持续多轮对话的单 Agent Harness。

## 运行流程

```text
用户输入
  → prepare_turn
  → compact_context
  → agent
      ├─ 直接回答 → END
      ├─ load_skill → execute_tools → 临时注入 Skill → agent
      ├─ Tool Calling → execute_tools → agent
      └─ 达到工具轮次上限 → force_finish → END
```

核心文件：

- `graph.py`：Agent Loop、Tool Runtime、停止条件。
- `memory.py`：上下文预算、安全切分和滚动摘要。
- `models.py`：Harness State、Running Summary、Visual Memory、Token Ledger、Tool Trace。
- `tools.py`：游戏资料/Wiki/攻略与实时资讯搜索。
- `skills/`：Agent Skills 元数据、工作流、references 与安全加载器。
- `image_memory.py`：历史图片到 Running Summary 视觉记忆的转换。
- `attachments.py`：预留的文档校验与文本提取能力。

## 五层模型上下文

每次调用模型前，Harness 动态组装：

```text
System Prompt
+ Running Summary
+ Active Skill Instructions（本轮按需）
+ Recent Messages
+ Current Turn / Tool Results
```

PostgreSQL Checkpoint 保存线程状态，但模型不会直接看到所有历史 Checkpoint。模型可见内容由 `ContextManager` 按预算选择。聊天页面在 PostgreSQL 中另存一份不可变 Transcript，因此模型上下文被自动压缩后，用户仍能在左侧历史会话中查看完整聊天记录。

## 当前轮多模态输入

点击输入框左侧加号后，浏览器读取本地图片并编码成 Data URL，和文字一起作为当前 `HumanMessage` 发送。主模型在同一次调用中直接看到文字和原图；只有旧轮次被压缩时，原图才转换为 `RunningSummary.visual_memories` 中的结构化视觉记忆。

```text
选择本地文件
→ 浏览器预览并编码 Data URL
→ ChatRequest 校验（最多 5 个、单个 10MB、合计 20MB）
→ 文字块 + 图片块进入同一 HumanMessage
→ 主模型联合理解文字与图片
→ 旧轮次过期时才生成图片结构化摘要
```

当前阶段只接收图片附件。PostgreSQL Transcript 保存图片内容以恢复聊天展示；LangGraph Checkpoint 保存当前多模态消息。较早轮次进入 Running Summary 时只保留结构化图片语义，避免原图永久占用模型上下文。

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
GAME_MAX_TOOL_ROUNDS=3
```

Harness 采用与 DeepSeek Harness 相同的默认比例：在有效窗口达到 80% 时触发压缩，并逐字保留窗口 16% 的近期表层。64K 有效窗口对应约 51.2K 的触发线和约 10.2K 的近期原文预算。Token Ledger 增量记录每条消息的估算值，并加入 System Prompt、Tool Schema 等协议开销；API 返回 `usage.input_tokens` 后会平滑校准协议开销，但本地计数仍是压缩前的安全估算，不冒充供应商精确计费。

每次模型请求前都会检查压力。触发压缩后先裁剪较早的大型 Tool Result；重新测量后仍超过触发线，才执行结构化摘要：

```text
New Running Summary
= Compress(Old Running Summary + Newly Expired Complete Turns)
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

模型可见工具保持为两个：

- `load_skill(name, resource)`：激活专业工作流或按需 reference，只返回加载确认；正文由 Harness 临时注入，不写入持久消息。
- `web_search(query, depth)`：模型自主决定是否调用，并通过 `quick` 或 `research` 选择快速查询或多来源研究；Query 可以来自文字、图片理解和对话上下文。

## Agent Skills 与渐进式披露

启动时 Registry 扫描 `skills/*/SKILL.md`，只把 `name + description` 目录加入 System Prompt。模型判断任务需要专业流程时调用 `load_skill`，Harness 将完整 `SKILL.md` 加入本轮后续模型调用；只有 Skill 明确要求且当前任务需要时，模型才继续加载 `references/*.md`。

```text
元数据目录（始终加载）
→ SKILL.md（Skill 激活后加载）
→ references/*.md（当前分支需要时加载）
```

当前包含：

- `gameplay-guide`：任务路线、Boss、地图、解谜和当前画面下一步指导。
- `game-build-advisor`：基于账号、装备、属性和资源的配队与养成建议。
- `game-news`：最新公告、版本动态、行业新闻和传闻核验。

`HarnessState.active_skills`、`loaded_skill_resources` 和 `skill_trace` 记录本轮激活情况；`prepare_turn` 在新一轮开始时重置。Skill 正文始终从本地可信目录读取，不进入聊天历史。

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

## 启动

```bash
docker compose up -d postgres
conda activate black
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

打开 `http://127.0.0.1:8001/`。左侧展示持久化历史会话，中间是聊天区，右侧展示 Tool Trace、上下文预算、Running Summary 和自动压缩状态。

调试接口：

- `GET /ai/sessions`：列出历史会话。
- `GET /ai/sessions/{session_id}/messages`：读取完整展示 Transcript。
- `GET /ai/sessions/{session_id}/runs`：读取最近的逐轮 Harness 执行轨迹。
- `GET /ai/sessions/{session_id}/state`：检查完整 LangGraph State。
