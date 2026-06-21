# Project Memory

日期：2026-06-18

仓库：`yglovemax/life2`

项目：Nexa 占卜 APP 的 AI API 管理后台与后端服务。

## 一句话目标

做一个可服务星盘、八字、日运、聊天咨询、资料训练和模型路由的 AI 后台。平台学习方式不是修改大模型权重，而是把资料结构化入库、发布成知识版本，再在客户对话和模块输出时检索使用。

## 当前产品定位

- 后台团队用它管理 AI 模块、Prompt、字段契约、模型、输出策略、测试、问题、发布和回滚。
- 训练团队用它上传资料、GitHub 导入资料、让训练助理生成结构化知识草稿，再发布到检索环境。
- 客户端前端团队用 `/api/app/*` 接口创建用户、保存本命资料、发起聊天、读取正式模块输出。
- 生产底座正在从本地 MVP 升级到 Postgres、pgvector、Redis worker、对象存储、限流和批量重建能力。

## 已落地能力

- 后台登录、管理员会话、敏感接口保护。
- App Key 管理、撤销和安全审计。
- 页面、模块、Prompt、字段契约、模型配置、输出策略。
- 模型供应商 Key 管理和脱敏展示。
- 模型路由预览、输出编排、Fallback 和调用追踪。
- 模块测试、批量测试、人工评分、问题追踪。
- 发布、灰度、上线、回滚和版本快照。
- 知识库手动录入、文件上传、GitHub 导入、轻量检索。
- 知识资料归档、恢复、未引用资料硬删除和重复资料提示。
- 重复知识组查询和安全合并归档，合并动作写入审计。
- 知识清理建议清单：只读返回可合并重复源和可删除归档未引用源。
- AI 训练运行：同步、队列、失败重试、取消、发布。
- 训练草稿发布前质检：阻断高风险词、绝对化承诺、医疗/法律/投资风险和低置信度内容。
- 训练质检审计：训练详情返回 `quality_events`，全局审计记录通过、阻断和 override。
- App 用户、出生资料、本命盘快照、八字输入快照。
- 聊天会话、消息记录、同步/流式回复。
- 长期记忆条目、长期记忆摘要、自动记忆抽取、异步摘要任务。
- mock embedding、OpenAI embedding provider、embedding 批量重建。
- 数据库运行时切换、Alembic 迁移、pgvector 向量列写入和 PG 检索分支。
- 对象存储、任务队列、限流运行时工厂。
- worker 命令入口和任务协议。
- Redis 队列、限流共享连接和运行状态检查。
- 八字页面、八字日运模块、八字事实自动注入。
- 八字算法服务 HTTP 占位和 mock 接线。

## 关键技术决策

- 框架：FastAPI + SQLAlchemy + SQLite 本地开发，生产计划使用 Postgres。
- 迁移：Alembic 管理 schema。
- 前端：当前仓库保留后台管理 MVP 静态页面，客户前端由外部团队集成 `/api/app/*`。
- 学习方式：RAG/知识库检索，不训练或修改基础模型权重。
- 训练资料流程：资料上传或导入 -> 解析 -> AI 结构化草稿 -> 人工发布 -> 知识检索。
- 用户记忆：不把全部历史聊天塞进 prompt；保留用户资料、长期摘要、少量可检索记忆和最近对话。
- 模型调用：默认 mock，生产通过 `NEXA_MODEL_CALL_MODE=live` 和 `NEXA_OPENAI_API_KEY` 开启真实模型。
- 模型供应商 Key：数据库只保存哈希和前缀，不保存可逆明文。
- App 鉴权：默认 `dev-app-token` 仅本地使用，生产要替换。
- 队列：本地可用 memory，独立 API/worker 进程必须切 Redis；`/api/runtime/status` 可检查 Redis 连通和队列积压。
- embedding：默认 mock，生产可切 OpenAI；切换 provider/model/dimensions 后用 `/api/embeddings/rebuild` 重建旧数据。
- pgvector：迁移、向量列写入和 PG 检索分支已接；SQLite 本地仍以平台侧 embedding 相似度兜底。

## 当前运行方式

本地服务：

```bash
uvicorn app.main:app --reload --port 8812
```

本地地址：

- 后台：`http://127.0.0.1:8812/admin`
- API 文档：`http://127.0.0.1:8812/docs`

默认本地账号：

- 后台：`admin / admin123`
- App Key：`dev-app-token`

worker：

```bash
python -m app.worker once
python -m app.worker once 20
python -m app.worker
```

## 核心接口入口

- 健康检查：`GET /api/health`
- 运行状态：`GET /api/runtime/status`
- 后台登录：`POST /api/auth/login`
- App 用户：`POST /api/app/users`
- 本命资料：`PUT /api/app/users/{user_id}/birth-profile`
- 盘面快照：`GET /api/app/users/{user_id}/chart`
- 盘面计算/回写：`POST /api/app/users/{user_id}/chart/calculate`
- 聊天回复：`POST /api/app/chat/sessions/{session_id}/reply`
- 聊天流式：`GET /api/app/chat/sessions/{session_id}/stream`
- 知识搜索：`POST /api/knowledge/search`
- 知识资料归档：`POST /api/knowledge-sources/{source_id}/archive`
- 知识资料恢复：`POST /api/knowledge-sources/{source_id}/restore`
- 知识资料删除：`DELETE /api/knowledge-sources/{source_id}`
- 重复知识组：`GET /api/knowledge/duplicates`
- 重复知识合并：`POST /api/knowledge-sources/{source_id}/merge`
- 知识清理建议：`GET /api/knowledge/cleanup-recommendations`
- 训练运行：`POST /api/training/runs`
- 训练质检报告：`GET /api/training/runs/{run_id}/quality-report`
- 训练质检审计：`GET /api/training/runs/{run_id}` 返回 `quality_events`
- embedding 重建：`POST /api/embeddings/rebuild`

完整接口说明看：

- `backend-integration.md`
- `frontend-api-contract.md`
- `app-api.md`

## 任务队列类型

- `training.run`
- `memory.summarize`
- `embedding.rebuild`

## 明确边界

- 当前不做大模型权重微调。
- 当前不保存模型供应商 Key 明文。
- 当前八字排盘引擎不是完整上线版，已有的是输入快照、mock 计算、外部 HTTP 服务占位。
- 当前 pgvector 列、索引、向量写入和 PG 检索分支已准备；真实效果还需要在 PostgreSQL 环境冒烟验证。
- 当前收费、订单、会员、支付最后做，尚未进入实现。
- 当前后台 UI 是管理 MVP，不代表最终商业化后台视觉。
- 当前客户聊天前端由外部团队开发，本仓库主要提供后端接口和后台管理能力。
- 本仓库是独立项目，不与 `life`、`astro_daily_agent` 或其他旧项目混写。

## 下一步建议

1. 在服务器上部署真实 Redis，跑 API 进程和 worker 进程分离冒烟验证。
2. 在服务器上接 Postgres + pgvector，跑真实向量列写入和 ANN 检索冒烟。
3. 把 `app/services.py` 按领域拆分，降低单文件复杂度。
4. 完善训练中心的知识版本清理、重复合并和质检规则。
5. 接真实八字排盘服务，补大运、流年、十神、旺衰等结构。
6. 给前端团队交付稳定的 `/api/app/*` 合同和示例集合。
7. 最后再做收费、会员、权限套餐和用量计费。
