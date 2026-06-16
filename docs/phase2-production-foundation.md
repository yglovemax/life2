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

## 当前边界

- `NEXA_TASK_QUEUE_BACKEND=memory` 只适合同进程本地联调。
- 如果训练任务要由独立 worker 进程消费，必须切到 `RedisTaskQueue`，也就是配置：
  - `NEXA_TASK_QUEUE_BACKEND=redis`
  - `NEXA_REDIS_URL=...`
- `RedisTaskQueue` 和 `RedisRateLimiter` 现在会复用同一个 Redis client，减少同进程重复建连。
- 当前仓库已经把 worker 入口和任务协议接好了，但跨进程共享队列这一步还差真实 Redis 环境。

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

状态会经历：

- `queued`
- `running`
- `completed`
- `failed`

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

- 把 `memory.summarize` 也迁成任务化。
- 把 `RedisTaskQueue` 和 `RedisRateLimiter` 接到真实 `NEXA_REDIS_URL`。
- 加 Postgres 专用迁移和 pgvector 字段。
- 把训练失败重试和死信策略补上。
