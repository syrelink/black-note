# Multi-Agent RAG 最佳实践（2026）

> 整理自 MarsDevs、MLOps Community、arXiv 等资料，结合 black-note 项目实际情况。

---

## 一、RAG 的演化路径

```
Naive RAG（2023）
    ↓ 加评估和循环
Modular RAG / Agentic RAG（2024）
    ↓ 加知识图谱
GraphRAG（2024，微软开源）
    ↓ 加多 Agent 分工
Multi-Agent RAG（2025-2026 主流）
```

核心转变：把 RAG 从**一次性流水线**变成**循环决策过程**，让 LLM 自己决定要不要检索、检索结果够不够好、需不需要重试。

---

## 二、核心概念辨析

三者解决的是同一个问题：**如何把复杂任务拆解并路由给最合适的处理单元**。

意图识别被 Router 取代了，Router 和 Multi-Agent 是互补关系不是替代关系。对笔记项目来说，Agentic RAG Router 就够了，上 Multi-Agent 是过度设计。

| | 意图识别 | Agentic RAG Router | 多 Agent |
|---|---|---|---|
| 决策方式 | 分类（离散类别） | 推理（可解释） | 规划 + 分工 |
| 类别 | 预定义、固定 | 可动态扩展 | 专家各自独立 |
| 上下文 | 当前输入 | 对话历史 + 中间结果 | 跨 Agent 共享状态 |
| 失败处理 | 兜底 fallback | 重试、换策略 | 重新分配子任务 |

**演化关系：**
```
规则路由（if/else）
    ↓
意图识别（ML 分类器）
    ↓
LLM 路由（Adaptive RAG Router）
    ↓
单 Agent 自主决策（Agentic RAG）
    ↓
多 Agent 协作（专家分工）
```

---

## 三、生产级架构：三层分工

```
┌─────────────────────────────────────┐
│         Orchestrator Agent          │  ← 只负责规划和分发
│   分析问题 → 拆子任务 → 聚合结果      │
└──────────┬──────────────────────────┘
           │ 分发
    ┌──────┼──────────┐
    ▼      ▼          ▼
Retrieval  Synthesis  Critic
 Agent      Agent     Agent
检索+评分   生成答案   检查幻觉
```

每个 Agent 独立扩缩容，这是与单 Agent 最大的工程区别。

---

## 四、五种主流生产模式

| 模式 | 适合场景 | 核心机制 |
|------|---------|---------|
| **Corrective RAG (CRAG)** | 通用问答 | 检索 → 打分 → 不好就重写查询再检索 |
| **Adaptive RAG** | 混合复杂度 | 先分类问题难度，选不同深度的流程 |
| **Multi-hop Decompose** | 复杂推理 | 大问题 → 子问题 → 分别检索 → 聚合 |
| **GraphRAG** | 跨文档关联 | 知识图谱 + 向量，处理"连点成线"问题 |
| **HyDE** | 向量召回差 | 先生成假设答案，用答案向量检索 |

> 据 2026 年 5 月 MLOps 社区基准：GraphRAG + Agentic 循环在跨文档问题上比 Naive RAG 减少约 **62% 幻觉**，但延迟和成本更高。

### CRAG 详解

**CRAG = Corrective RAG（纠正式检索增强生成）**

论文：*Corrective Retrieval Augmented Generation*（2024，arXiv 2401.15884）

核心思想：检索完之后**不直接用**，先让 LLM 判断检索结果够不够好，不好就纠正（rewrite + retry）。

```
传统 RAG（一次性）：
  query → 检索 → 生成   ← 检索质量好坏都直接用

CRAG（有纠正机制）：
  query → 检索 → 评分
                  ↓ 好 → 生成
                  ↓ 差 → 改写 query → 重新检索 → 评分 → 生成
```

三个字拆开理解：

| 字 | 含义 |
|---|---|
| **Corrective** | 有纠错机制，发现检索不好就主动修正 |
| **Retrieval** | 检索这一步（BM25 + 向量） |
| **Augmented Generation** | 用检索结果增强 LLM 生成 |

**在 black-note 项目里的对应实现：**

- **Corrective** = Grader 批量打分 + query rewrite + retry loop（最多 2 次）
- **Retrieval** = BM25 + Qdrant 混合检索 + FlashRank 重排序
- **Augmented Generation** = Agent 的 `llm_call` 节点用检索结果生成回答

```python
# search_notes 内部 CRAG 流程
for attempt in range(MAX_RETRIES + 1):   # 最多 3 轮

    if attempt > 0:
        current_query = rewriter_llm.invoke(...)  # 改写 query

    raw_docs = retriever.invoke(current_query)    # 混合检索
    reranked  = rerank_docs(current_query, ...)   # FlashRank 重排

    grade_result = grader_llm.invoke(...)         # 1次LLM批量打分
    relevant = [doc for doc, s in zip(reranked, grade_result.scores) if s == "yes"]

    if len(relevant) >= 2 or attempt == MAX_RETRIES:
        break  # 够用了，或已用完重试次数
```

---

## 五、Modular RAG：模块化设计思想

2026 年社区共识是 **Modular RAG**，每个组件可以独立替换：

```
[Query Transform]  → 改写 / 分解 / HyDE，可插拔
[Retriever]        → 向量 / BM25 / 知识图谱，可切换
[Reranker]         → FlashRank / ColBERT / LLM Rerank
[Grader]           → 相关性评分，可以是小模型
[Generator]        → 主力 LLM
[Critic]           → 幻觉检测，可以是独立服务
```

好处：每一层独立优化，不需要动整个系统。

---

## 六、框架选型（2026 主流）

### 单服务内 Agent 控制流 → LangGraph

有状态 Agentic RAG 首选。优势：
- 图结构可视化
- Time-travel 调试（可回放任意步骤）
- Checkpoint 支持 human-in-the-loop
- MongoDB / SQLite checkpointer

### 检索/索引层 → LlamaIndex

LangGraph 管控制流，LlamaIndex 管文档处理和检索，是目前最常见的组合：

```python
llama_index_retriever  # 负责混合检索、重排序
langgraph_graph        # 负责 Agent 循环和状态管理
```

### 跨服务 Agent 通信 → A2A 协议

2025 年 4 月 Google 发布（LangChain 参与制定）。解决**不同服务的 Agent 怎么互相调用**的问题。

基于 HTTP + SSE + JSON-RPC，每个 Agent 暴露一个 Agent Card（能力描述），其他 Agent 通过 A2A 协议发现和调用：

```
笔记 Agent  ←──A2A──→  日历 Agent
    ↑                       ↑
    └─────── Orchestrator ───┘
```

---

## 七、对 black-note 项目的升级建议

按收益/成本比排序：

| 优先级 | 升级项 | 预计工作量 | 收益 |
|--------|--------|-----------|------|
| ⭐⭐⭐ | Query Rewriting | 1 天 | 召回率提升最明显 |
| ⭐⭐⭐ | Relevance Grading (CRAG) | 1 天 | 过滤噪声，减少幻觉 |
| ⭐⭐ | Adaptive Router | 1 天 | 简单/复杂问题分流 |
| ⭐⭐ | Modular 重构 | 2 天 | 架构可扩展 |
| ⭐ | GraphRAG | 1 周 | 笔记关联强时再加 |
| ⭐ | A2A 跨服务 | 未来 | 扩展成多微服务时 |

**Query Rewriting + CRAG 已在 `search_notes` 工具中完成实现。**

---

## 八、简历写法参考

**不好的写法（流水账）：**
> 使用 LangGraph 实现了 RAG 功能，集成了 Qdrant 向量数据库

**好的写法（有设计决策 + 量化）：**
> 设计并实现基于 LangGraph 的 Agentic RAG 系统，引入查询改写（Query Rewriting）与检索相关性评分（CRAG Grader）节点，将多轮对话中的笔记召回准确率提升约 30%；系统支持动态决策是否重新检索，相比 Naive RAG 在复杂查询场景下答案相关性显著改善

**关键词：**
`Agentic RAG` · `CRAG (Corrective RAG)` · `LangGraph 状态机` · `Retrieval Grading` · `Query Rewriting` · `混合检索（BM25 + 向量）` · `Modular RAG` · `A2A Protocol`

---

## 九、实际案例对比（以小黑书为例）

### 案例一：Agentic RAG Router（单 Agent）

用户问：**"帮我总结一下我最近写的关于健身的笔记"**

```
用户输入
   ↓
[Router 节点] LLM 判断问题复杂度
   │
   ├─ 判断结果：需要检索 + 需要汇总多篇
   ↓
[Query Rewriting] 改写为："健身 训练 锻炼 运动"
   ↓
[Retriever] BM25 + Qdrant 检索 top20
   ↓
[CRAG Grader] 批量打分，过滤掉不相关的
   │
   ├─ 相关文档 >= 2 篇 → 直接生成
   └─ 相关文档 < 2 篇 → 重写查询再检索（最多2次）
   ↓
[Generator] 汇总生成答案
```

**整个过程只有一个 LLM 在做所有决策**，像一个人又想又干。代码上就是 LangGraph 的一个图，所有节点共享同一个 State。

---

### 案例二：Multi-Agent（多 Agent 协作）

用户问：**"根据我的健身笔记，帮我制定下周的训练计划，并提醒我周一到周五的执行时间"**

这个问题涉及两个独立能力：查笔记 + 管日历，单个 Agent 搞不定。

```
用户输入
   ↓
[Orchestrator Agent]  ← 只负责规划
   Step 1：从笔记中提取健身内容
   Step 2：根据内容写入日历提醒
   ↓ 分发任务
   │
   ├──→ [笔记 Agent]        ← 专门查笔记
   │      检索健身相关笔记 → 返回结构化数据
   │
   └──→ [日历 Agent]        ← 专门管日历
          调用日历 API 创建周一到周五提醒
   ↓
[Orchestrator Agent] 聚合两个 Agent 的结果
   ↓
输出："已根据你的笔记制定训练计划，并创建了5个日历提醒..."
```

**每个 Agent 是独立的服务**，通过 A2A 协议通信，各自可以独立部署和扩容。

---

### 核心区别

| | Agentic RAG Router | Multi-Agent |
|---|---|---|
| 决策者 | 一个 LLM，自己决定下一步 | Orchestrator 规划，Sub-agent 执行 |
| 能力边界 | 同一个知识库内 | 跨系统、跨工具、跨服务 |
| black-note 现阶段 | 够用 ✅ | 除非接入日历/邮件等外部系统才需要 |

---

## 参考资料

- [Agentic RAG: The 2026 Production Guide | MarsDevs](https://www.marsdevs.com/guides/agentic-rag-2026-guide)
- [10 RAG Architectures in 2026 | Techment](https://www.techment.com/blogs/rag-architectures-enterprise-use-cases-2026/)
- [Best Multi-Agent Frameworks in 2026 | GuruSup](https://gurusup.com/blog/best-multi-agent-frameworks-2026)
- [Corrective RAG 论文 | arXiv 2401.15884](https://arxiv.org/abs/2401.15884)
- [Agentic RAG Survey | arXiv 2501.09136](https://arxiv.org/html/2501.09136v4)
- [Next-Generation Agentic RAG with LangGraph 2026 | Medium](https://medium.com/@vinodkrane/next-generation-agentic-rag-with-langgraph-2026-edition-d1c4c068d2b8)
