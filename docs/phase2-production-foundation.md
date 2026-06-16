# Phase 2 Production Foundation

日期：2026-06-16

第二期先不追求一次性把 Postgres、Redis、对象存储、worker、部署全部做满，而是先把运行主干接通。

## 当前已落地

- 运行时工厂：
  - `NEXA_OBJECT_STORAGE_BACKEND`
  - `NEXA_TASK_QUEUE_BACKEND`
  - `NEXA_RATE_LIMIT_BACKEND`
- 训练运行支持两种模式：
  - `sync`
  - `queued`
- 队列任务类型第一版：
  - `training.run`
- worker 命令入口：
  - `python -m app.worker once`
  - `python -m app.worker`
- Alembic 初始化：
  - `alembic upgrade head`

## 当前边界

- `NEXA_TASK_QUEUE_BACKEND=memory` 只适合同进程本地联调。
- 如果训练任务要由独立 worker 进程消费，必须切到 `RedisTaskQueue`，也就是配置：
  - `NEXA_TASK_QUEUE_BACKEND=redis`
  - `NEXA_REDIS_URL=...`
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

持续运行 worker：

```bash
python -m app.worker
```

## 下一步

- 把 `memory.summarize` 也迁成任务化。
- 把 `RedisTaskQueue` 和 `RedisRateLimiter` 接到真实 `NEXA_REDIS_URL`。
- 加 Postgres 专用迁移和 pgvector 字段。
- 把训练失败重试和死信策略补上。
