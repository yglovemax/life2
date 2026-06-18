# Phase 2 Production Foundation

日期：2026-06-16

第二期先不追求一次性把 Postgres、Redis、对象存储、worker、部署全部做满，而是先把运行主干接通。

## 当前已落地

- 数据库运行时工厂：
  - `NEXA_DATABASE_URL`
- 运行时工厂：
  - `NEXA_OBJECT_STORAGE_BACKEND`
  - `NEXA_TASK_QUEUE_BACKEND`
  - `NEXA_RATE_LIMIT_BACKEND`
- 训练运行支持两种模式：
  - `sync`
  - `queued`
- 队列任务类型第一版：
  - `training.run`
  - `memory.summarize`
  - `embedding.rebuild`
- 失败训练重试接口：
  - `POST /api/training/runs/{run_id}/retry`
- 训练队列观测接口：
  - `GET /api/training/queue-status`
- 训练取消接口：
  - `POST /api/training/runs/{run_id}/cancel`
- worker 命令入口：
  - `python -m app.worker once`
  - `python -m app.worker once 20`
  - `python -m app.worker`
- Alembic 初始化：
  - `alembic upgrade head`
- PostgreSQL / pgvector 就绪层：
  - `20260617_0002_pgvector_embeddings.py`
  - PostgreSQL 下自动 `CREATE EXTENSION IF NOT EXISTS vector`
  - 为 `knowledge_chunks` 和 `memory_items` 准备 `vector(1536)` embedding 列
  - 准备 ivfflat cosine 索引
- Embedding 入库第一版：
  - 知识片段创建时写入 `embedding_model`、`embedding_hash`、`embedding_payload`
  - 用户长期记忆创建时写入同样的 embedding 元数据
  - 本地默认使用确定性 mock embedding，便于测试和无密钥开发
  - 支持 `NEXA_EMBEDDING_PROVIDER=openai` 调用 OpenAI `POST /embeddings`
  - `/api/knowledge/search` 在关键词分数不足时使用 mock embedding 相似度兜底排序
  - 支持 `POST /api/embeddings/rebuild` 对知识片段和用户记忆批量重建 embedding
- 运行时状态检查：
  - `GET /api/runtime/status`

## 当前边界

- `NEXA_TASK_QUEUE_BACKEND=memory` 只适合同进程本地联调。
- 如果训练任务要由独立 worker 进程消费，必须切到 `RedisTaskQueue`，也就是配置：
  - `NEXA_TASK_QUEUE_BACKEND=redis`
  - `NEXA_REDIS_URL=...`
- `RedisTaskQueue` 和 `RedisRateLimiter` 现在会复用同一个 Redis client，减少同进程重复建连。
- 当前仓库已经把 worker 入口和任务协议接好了，但跨进程共享队列这一步还差真实 Redis 环境。
- 当前 pgvector 迁移只在 PostgreSQL 方言下执行；SQLite 本地开发会跳过 vector 列。
- 当前默认 embedding provider 是 mock，不调用外部模型；设置 `NEXA_EMBEDDING_PROVIDER=openai` 且配置 `NEXA_OPENAI_API_KEY` 后，会调用 OpenAI embedding 接口。pgvector ANN 查询会在后续接入。

## 训练异步化接口

```http
POST /api/training/runs
```

同步执行：

```json
{
  "source_id": 1,
  "simulate_model_response": "{\"chunks\":[]}"
}
```

队列执行：

```json
{
  "source_id": 1,
  "run_mode": "queued",
  "simulate_model_response": "{\"chunks\":[]}"
}
```

队列返回重点字段：

```json
{
  "id": 12,
  "run_mode": "queued",
  "status": "queued",
  "task_id": "task_xxx"
}
```

前端或后台轮询：

```http
GET /api/training/runs/{run_id}
```

失败后可直接重试：

```http
POST /api/training/runs/{run_id}/retry
```

示例：

```json
{
  "run_mode": "queued",
  "simulate_model_response": "{\"chunks\":[...]}"
}
```

排队中可以取消：

```http
POST /api/training/runs/{run_id}/cancel
```

查看当前队列：

```http
GET /api/training/queue-status
```

返回重点字段：

```json
{
  "backend": "memory",
  "pending_tasks": 3,
  "runs": {
    "queued": 2,
    "running": 0,
    "completed": 10,
    "failed": 1,
    "published": 0,
    "canceled": 1
  },
  "queued_run_ids": [12, 13]
}
```

## Embedding 批量重建

```http
POST /api/embeddings/rebuild
```

同步重建某份知识源和某个用户记忆：

```json
{
  "target": "all",
  "run_mode": "sync",
  "source_id": 12,
  "user_id": 34,
  "force": true
}
```

队列重建某份知识源：

```json
{
  "target": "knowledge",
  "run_mode": "queued",
  "source_id": 12,
  "limit": 1000,
  "force": true
}
```

返回重点字段：

```json
{
  "status": "queued",
  "run_mode": "queued",
  "target": "knowledge",
  "processed": 0,
  "knowledge_chunks": 0,
  "memory_items": 0,
  "embedding_provider": "openai",
  "embedding_model": "text-embedding-3-small",
  "embedding_dimensions": 1536,
  "task_id": "task_xxx"
}
```

worker 会消费 `embedding.rebuild` 任务。生产环境建议使用 Redis 队列，避免 API 进程和 worker 进程之间任务不共享。

## 数据库 / pgvector 状态

```http
GET /api/runtime/status
```

返回重点字段：

```json
{
  "database": {
    "backend": "postgresql",
    "safe_url": "postgresql+psycopg://nexa:***@db:5432/nexa",
    "connected": true
  },
  "pgvector": {
    "planned": true,
    "extension": "vector",
    "installed": true,
    "ready": true,
    "dimensions": 1536,
    "embedding_model": "text-embedding-3-small",
    "embedding_provider": "openai",
    "target_tables": ["knowledge_chunks", "memory_items"],
    "index_type": "ivfflat_cosine"
  }
}
```

相关环境变量：

- `NEXA_DATABASE_URL`
- `NEXA_EMBEDDING_PROVIDER`
- `NEXA_EMBEDDING_MODEL`
- `NEXA_EMBEDDING_DIMENSIONS`

状态会经历：

- `queued`
- `running`
- `completed`
- `failed`

## 聊天记忆摘要异步化

聊天回复接口新增可选参数：

- `memory_run_mode=sync`
- `memory_run_mode=queued`

当前策略：

- `memory_items` 仍然同步创建，保证前端能立刻拿到本轮记忆条目。
- `memory_summary` 在 `queued` 模式下交给 `memory.summarize` worker 任务处理。
- SSE 的 `memory` 事件现在会带：
  - `summary_status`
  - `task_id`

## 命令

安装依赖：

```bash
pip install -r requirements.txt
```

执行迁移：

```bash
alembic upgrade head
```

单次处理一个队列任务：

```bash
python -m app.worker once
```

单次最多处理 20 个任务：

```bash
python -m app.worker once 20
```

持续运行 worker：

```bash
python -m app.worker
```

## 下一步

- 把 `RedisTaskQueue` 和 `RedisRateLimiter` 接到真实 `NEXA_REDIS_URL`。
- 把 mock 相似度搜索升级为 PostgreSQL/pgvector ANN 查询。
- 增加 embedding 批量重建和版本迁移任务。
- 把训练失败重试和死信策略补上。
- 把聊天记忆条目的落库也继续拆向异步批处理。
