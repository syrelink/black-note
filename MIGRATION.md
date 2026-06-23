# black-note 迁移说明

## 背景

原项目采用双服务架构：

```
black-note-app (Vue 前端)
    ↓
black-note-server (Spring Boot :8080)  ←→  MySQL / Redis / RabbitMQ / MinIO
    ↓ HTTP 回调
black-note-ai (FastAPI :8001)          ←→  ChromaDB / SQLite
```

迁移后，所有业务逻辑合并到单个 FastAPI 服务，彻底移除 Spring Boot、RabbitMQ、MySQL、ChromaDB、SQLite：

```
black-note-app (Vue 前端)
    ↓
black-note-ai (FastAPI :8001)
    ↕
  MongoDB    ← 主数据库（用户、笔记、关注、点赞、会话）
  Qdrant     ← 向量数据库（语义检索，替代 ChromaDB）
  Redis      ← 缓存 / Feed ZSet / Token / Celery broker
  MinIO      ← 图片存储
    ↕
  Celery worker（独立进程，处理向量同步）
```

---

## 技术选型说明（2026 年最佳实践）

### 为什么选择 MongoDB

| 原因 | 说明 |
|------|------|
| 文档天然匹配 | 笔记本身就是文档（title、content、images 数组），无需 ORM 映射 |
| 原生数组字段 | `images: list[str]` 直接存储，消除逗号分隔字符串的 hack |
| 灵活 schema | 后续扩展字段无需 ALTER TABLE |
| Beanie ODM | Pydantic v2 原生集成，类型安全，异步支持完善 |
| LangGraph 集成 | `langgraph-checkpoint-mongodb`（2026-05 发布）原生支持 MongoDB checkpointer |
| 现有"关系"已在 Redis | 关注关系、Feed ZSet、点赞集合均在 Redis，MongoDB 不需要强关系查询 |

### 为什么选择 Qdrant

| 原因 | 说明 |
|------|------|
| 单二进制、零依赖 | Rust 编写，部署比 ChromaDB 更简单可靠 |
| 原生过滤检索 | payload 过滤与向量搜索在同一次调用中完成，无需后置过滤 |
| 生产就绪 | 支持集群、RBAC、快照，ChromaDB 是嵌入式库不适合生产 |
| 2026 年社区 | 2026 年向量库首选，LangChain 官方 `langchain-qdrant` 活跃维护 |

---

## 架构对照

| 层次 | Java (Spring Boot) | Python (FastAPI) |
|------|--------------------|------------------|
| 框架 | Spring Boot 3 | FastAPI + uvicorn |
| 主数据库 | MySQL + MyBatis-Plus | MongoDB + Beanie ODM (Motor) |
| 向量库 | ChromaDB | Qdrant |
| LangGraph checkpointer | SQLite (AsyncSqliteSaver) | MongoDB (AsyncMongoDBSaver) |
| Redis | Spring Data Redis | redis-py async |
| 消息队列 | RabbitMQ | Celery + Redis（DB 1，复用已有 Redis） |
| 文件存储 | MinIO Java SDK | minio Python SDK |
| 密码哈希 | BCrypt (hutool) | passlib[bcrypt] |
| Token 认证 | UUID → Redis | UUID → Redis（key 格式完全相同） |

---

## 目录结构

```
black-note-ai/
├── app/
│   ├── main.py                  # 应用入口，注册所有路由 + AI 接口
│   ├── config.py                # 统一配置（从 .env 读取）
│   ├── database.py              # Motor client 单例 + Beanie init_db()
│   ├── redis_client.py          # 单例 Redis 异步客户端
│   ├── common.py                # Result<T> 响应体 + BusinessException
│   ├── auth.py                  # Token 认证依赖项（必须登录 / 可选登录）
│   ├── worker.py                # Celery 应用工厂（broker/backend 配置）
│   ├── tasks.py                 # Celery 任务定义（向量同步）
│   │
│   ├── models/                  # Beanie Document 模型（对应 MongoDB 集合）
│   │   ├── user.py              # users 集合
│   │   ├── note.py              # notes 集合
│   │   ├── follow.py            # follows 集合
│   │   ├── note_like.py         # note_likes 集合
│   │   └── chat_session.py      # chat_sessions 集合
│   │
│   ├── schemas/                 # Pydantic 请求/响应模型
│   │   ├── user.py
│   │   ├── note.py
│   │   ├── follow.py
│   │   ├── feed.py
│   │   └── chat_session.py
│   │
│   ├── routers/                 # API 路由（URL 路径与 Java 完全一致）
│   │   ├── user.py              # /user/*
│   │   ├── note.py              # /note/*
│   │   ├── follow.py            # /follow/*
│   │   ├── feed.py              # /feed
│   │   ├── file.py              # /file/upload
│   │   └── chat_session.py      # /chat/sessions/*
│   │
│   ├── services/                # 业务逻辑层（无 db 参数，直接调用 Beanie API）
│   │   ├── user_service.py
│   │   ├── note_service.py
│   │   ├── follow_service.py
│   │   ├── feed_service.py
│   │   ├── file_service.py
│   │   └── chat_session_service.py
│   │
│   ├── core/                    # AI 核心
│   │   ├── graph.py
│   │   ├── prompts.py
│   │   ├── rag.py               # Qdrant + BM25 混合检索
│   │   ├── schemas.py
│   │   ├── state.py
│   │   └── tools.py             # LangGraph 工具（MongoDB 查询）
│   │
│   └── storage/                 # 向量库管理
│       ├── build_index.py       # 全量建库（MongoDB → Qdrant）
│       ├── embeddings.py        # BGE-M3 embedding 单例
│       ├── sync.py              # 增量同步（async Motor + async Qdrant）
│       └── text_cleaner.py
│
├── requirements.txt
└── .env
```

---

## API 接口对照

所有接口 URL 与 Java 端完全一致，**前端无需任何修改**。

### 用户模块 `/user`

| 方法 | 路径 | 描述 | 认证 |
|------|------|------|------|
| POST | `/user/register` | 注册 | 否 |
| POST | `/user/login` | 登录，返回 token | 否 |
| GET  | `/user/{id}` | 获取用户信息 | 否 |
| PUT  | `/user/me` | 更新当前用户信息 | 是 |

### 笔记模块 `/note`

| 方法 | 路径 | 描述 | 认证 |
|------|------|------|------|
| POST   | `/note/publish` | 发布笔记 | 是 |
| GET    | `/note/{id}` | 获取笔记详情 | 可选 |
| PUT    | `/note/update/{id}` | 更新笔记 | 是 |
| DELETE | `/note/delete/{id}` | 删除笔记 | 是 |
| GET    | `/note/list` | 公开笔记列表（分页） | 可选 |
| GET    | `/note/list/{userId}` | 某用户的笔记列表 | 可选 |
| POST   | `/note/like/{noteId}` | 点赞 / 取消点赞 | 是 |
| GET    | `/note/like/count/{noteId}` | 点赞数 | 否 |
| GET    | `/note/like/status/{noteId}` | 是否已点赞 | 可选 |

### 关注模块 `/follow`

| 方法 | 路径 | 描述 | 认证 |
|------|------|------|------|
| POST | `/follow/{userId}` | 关注 / 取消关注 | 是 |
| GET  | `/follow/list/{userId}` | 关注列表 | 否 |
| GET  | `/follow/isFollow/{userId}` | 是否已关注 | 是 |
| GET  | `/follow/common/{userId}` | 共同关注 | 是 |

### Feed 流 `/feed`

| 方法 | 路径 | 描述 | 认证 |
|------|------|------|------|
| GET | `/feed?last_timestamp=0&page_size=10` | 关注流（游标翻页） | 是 |

### 文件 `/file`

| 方法 | 路径 | 描述 | 认证 |
|------|------|------|------|
| POST | `/file/upload` | 上传图片到 MinIO，返回 URL | 是 |

### AI 会话 `/chat/sessions`

| 方法 | 路径 | 描述 | 认证 |
|------|------|------|------|
| GET    | `/chat/sessions` | 获取当前用户的会话列表 | 是 |
| POST   | `/chat/sessions/{sessionId}` | 新建或更新会话标题 | 是 |
| DELETE | `/chat/sessions/{sessionId}` | 删除会话 | 是 |

### AI 对话

| 方法 | 路径 | 描述 | 认证 |
|------|------|------|------|
| POST | `/ai/chat` | 流式问答（SSE） | 是 |
| GET  | `/ai/health` | 健康检查（返回 Qdrant 索引数量） | 否 |

---

## Redis Key 设计（与 Java 保持一致）

| Key 格式 | 类型 | 含义 | TTL |
|----------|------|------|-----|
| `login:token:{token}` | String | token → userId（MongoDB ObjectId hex）| 60 min |
| `note:detail:{noteId}` | String (JSON) | 笔记详情缓存 | 30 min |
| `like:set:{noteId}` | Set | 点赞用户 ID 集合 | 永久 |
| `like:count:{noteId}` | String | 点赞数计数器 | 7 天 |
| `follow:{userId}` | Set | 该用户关注的用户 ID 集合 | 永久 |
| `feed:inbox:{userId}` | ZSet | Feed 收件箱（score = 时间戳 ms）| 永久 |

> Redis DB 0 供应用使用，DB 1 供 Celery broker/backend 使用，两者隔离。

---

## MongoDB 集合设计

| 集合 | 说明 | 关键索引 |
|------|------|---------|
| `users` | 用户，`username` 唯一索引 | `username (unique)` |
| `notes` | 笔记，`images` 为原生数组，`is_deleted` 为 bool | `user_id`, `(is_deleted, created_at)` |
| `follows` | 关注关系 | `(user_id, follow_user_id) unique`, `follow_user_id` |
| `note_likes` | 点赞记录 | `(user_id, note_id) unique`, `note_id` |
| `chat_sessions` | AI 对话会话，`session_id` 存 LangGraph UUID | `session_id (unique)`, `(user_id, updated_at)` |

> `ChatSession._id` 由 MongoDB 自动生成，`session_id` 字段单独存储 LangGraph UUID。

---

## 异步任务设计（RabbitMQ → Celery）

### 原则：只对真正慢的操作异步化

| 操作 | 耗时估算 | 处理方式 | 原因 |
|------|---------|---------|------|
| 点赞落库 | <10ms | 同步（请求内完成） | 单条 insert，极快 |
| 缓存删除 | <5ms | 同步 + try/except 日志 | Redis DEL，极快 |
| Feed 推送 | <50ms | 同步（请求内完成） | 批量 Redis ZADD，可接受 |
| 向量同步 | 1~10s | **Celery 异步** | BGE-M3 embedding 推理是唯一真正慢的操作 |

### Celery 关键配置

| 配置项 | 值 | 作用 |
|--------|-----|------|
| broker | `redis://localhost:6379/1` | 使用已有 Redis，DB 1 |
| backend | `redis://localhost:6379/1` | 任务结果存储 |
| `task_acks_late` | `True` | 执行完再 ACK，worker 崩溃不丢任务 |
| `max_retries` | 3 | 向量同步失败自动重试，间隔 30s |

---

## 环境配置 `.env`

```ini
# MongoDB
MONGODB_URL=mongodb://localhost:27017
MONGODB_DB=black_note

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=black_note_all

# Redis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=

# MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=syr
MINIO_SECURE=false

# AI（原有配置保持不变）
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
```

---

## 启动

```bash
cd black-note-ai

# 安装依赖
pip install -r requirements.txt

# 0. 全量建库（首次运行或数据迁移后）
python -m app.storage.build_index

# 1. 启动 FastAPI（主服务）
uvicorn app.main:app --port 8001 --reload

# 2. 启动 Celery worker（另一个终端，处理向量同步）
celery -A app.worker worker --loglevel=info

# 3. 可选：Flower 可视化监控
celery -A app.worker flower --port=5555

# API 文档
open http://localhost:8001/docs
```

---

## 已移除的组件

| 组件 | 原用途 | 处理方式 |
|------|--------|---------|
| Spring Boot JVM | 运行时 | 移除，不再需要 |
| MySQL | 主数据库 | MongoDB 替代 |
| SQLAlchemy / aiomysql | ORM / MySQL 驱动 | Beanie ODM + Motor 替代 |
| ChromaDB | 向量库（嵌入式）| Qdrant 替代（独立服务，生产就绪）|
| SQLite / AsyncSqliteSaver | LangGraph checkpointer | AsyncMongoDBSaver 替代 |
| RabbitMQ | 异步消息队列 | Celery + Redis 替代（仅向量同步需要异步）|
| Redisson | 分布式锁 | 点赞幂等改为 MongoDB 唯一索引保证 |
| hutool | 工具库 | Python 标准库 + passlib |

## <u>**如何把一个复杂任务，拆解并路由给最合适的处理单元？**</u>

