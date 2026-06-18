# Nexa AI API Admin

Nexa 占卜 APP 的 AI API 管理后台。

本项目按 `docs/requirements/Nexa占卜APP_AI_API管理后台_开发需求文档.md` 原版需求逐步实现。第一期目标是让团队可以围绕星座/占星页面完成模块管理、Prompt 调试、字段契约、模型选择、测试追踪、Fallback 和发布协作。

## 当前阶段

Phase 1 已完成第一版闭环：

- 模块中心和模块详情
- Prompt 五段式配置
- 字段契约配置
- 模型配置
- 模型供应商 Key 管理、模型路由和输出策略
- 真实模型调用适配层（默认 mock，可通过环境变量开启 OpenAI Responses API）
- 模型原始返回 JSON 校验、缺字段自动 Fallback
- 测试中心和人工评分
- 问题追踪和责任流转
- 知识库录入与轻量检索
- 成本中心和 Fallback 告警
- 发布中心、灰度、上线、回滚
- App 页面级 / 模块级 JSON API
- 训练资料上传、GitHub 导入和 AI 训练草稿发布 API
- 用户资料、本命资料、聊天会话、消息记录和长期记忆 API
- 八字基础资料、四柱快照和八字聊天上下文支持
- App 页面/模块渲染自动注入用户盘面快照和八字事实
- 八字日运渲染自动注入日期和 `daily_transit` 基础上下文
- 聊天回复编排和 SSE 流式回复 API
- 可配置对象存储 / 任务队列 / 限流运行时工厂
- App 聊天接口限流和 `X-RateLimit-*` 响应头
- 聊天自动记忆抽取和长期摘要更新
- 正式调用与测试调用隔离
- App Key 管理和安全审计
- 后台登录、管理员会话和敏感接口保护

Phase 2 已开始接入生产化底座：

- Alembic 迁移入口
- 数据库运行时工厂，可按 `NEXA_DATABASE_URL` 切换
- PostgreSQL/pgvector 迁移占位和运行状态检查
- 知识片段和用户记忆的 mock embedding 入库与语义检索兜底
- OpenAI embedding provider 接线和 embedding 批量重建接口
- 队列化训练运行
- 聊天长期记忆摘要异步队列
- 失败训练重试接口
- 训练队列状态接口和取消接口
- worker 命令入口
- 运行时存储 / 队列 / 限流后端工厂
- 八字算法服务 HTTP 接口占位和模拟接线

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8812
```

打开：

- 后台页面：http://127.0.0.1:8812/admin
- API 文档：http://127.0.0.1:8812/docs

本地默认后台账号为 `admin / admin123`。生产部署前请覆盖 `NEXA_ADMIN_USERNAME` 和 `NEXA_ADMIN_PASSWORD`。

模型调用默认不出网，方便本地开发和测试：

```bash
NEXA_MODEL_CALL_MODE=mock
```

生产需要真实调用 OpenAI 时设置：

```bash
export NEXA_MODEL_CALL_MODE=live
export NEXA_OPENAI_API_KEY="<openai_api_key>"
```

后台保存的模型供应商 Key 只做配置、脱敏展示和审计占位；实际运行时 Key 读取 `NEXA_OPENAI_API_KEY`，避免数据库保存可逆明文密钥。

生产化运行时可继续覆盖：

```bash
export NEXA_OBJECT_STORAGE_BACKEND=local
export NEXA_TASK_QUEUE_BACKEND=memory
export NEXA_RATE_LIMIT_BACKEND=memory
export NEXA_DATABASE_URL=sqlite:///./data/nexa_admin.db
export NEXA_REDIS_URL=redis://127.0.0.1:6379/0
export NEXA_APP_CHAT_RATE_LIMIT_COUNT=12
export NEXA_APP_CHAT_RATE_LIMIT_WINDOW_SECONDS=60
export NEXA_BAZI_CALC_MODE=mock
export NEXA_BAZI_API_URL=
export NEXA_BAZI_API_TOKEN=
export NEXA_EMBEDDING_PROVIDER=mock
export NEXA_EMBEDDING_MODEL=text-embedding-3-small
export NEXA_EMBEDDING_DIMENSIONS=1536
```

注意：`NEXA_TASK_QUEUE_BACKEND=memory` 仅适合同进程本地开发。独立 worker 进程要消费任务，需要切到 Redis 后端。

前端接口合同见：`docs/frontend-api-contract.md`
App 对接说明见：`docs/app-api.md`
后端集成边界见：`docs/backend-integration.md`
安全审计说明见：`docs/security.md`
旧项目复用清单见：`docs/reuse-inventory.md`
第二期底座说明见：`docs/phase2-production-foundation.md`

## 测试

```bash
pytest
```

## 迁移与 Worker

```bash
alembic upgrade head
python -m app.worker once
python -m app.worker once 20
python -m app.worker
```

## 项目边界

这是独立项目，只服务 Nexa AI API 管理后台，不与 `life`、`astro_daily_agent` 或其他旧项目混写。
