# 旧项目可复用资产梳理

日期：2026-06-16

## 来源

本次梳理了两个来源：

- 本地旧项目：`/Users/chenkai/python学习/hellow.py/astro_daily_agent`
- GitHub 旧仓库：`https://github.com/yglovemax/life`

GitHub `life` 仓库与本地 `astro_daily_agent` 主体一致，可以把它视为旧项目的代码来源。`life2` 继续保持独立项目，只从旧项目迁移可复用模块和设计，不混写旧目录。

## 验证结果

旧项目关键复用模块已跑过选择性测试：

```bash
astro_daily_agent/.venv/bin/python -m unittest \
  astro_daily_agent.tests.test_training_documents \
  astro_daily_agent.tests.test_github_import \
  astro_daily_agent.tests.test_training \
  astro_daily_agent.tests.test_llm \
  astro_daily_agent.tests.test_memory \
  astro_daily_agent.tests.test_scalable_model_router \
  astro_daily_agent.tests.test_scalable_schema -v
```

结果：`Ran 32 tests ... OK`

这说明上传资料解析、GitHub 导入、AI 训练解析、OpenAI/SSE、用户记忆、模型路由和 Postgres schema 草案都不是纯概念，具备迁移基础。

## 总体判断

`life2` 当前是新的 FastAPI + SQLAlchemy 后台管理骨架，已经完成模块、Prompt、字段、测试、发布、模型路由、输出校验和安全审计。

旧项目 `astro_daily_agent` 更像前一版实验场，里面已经有：

- 客户前台咨询编排
- 本命资料保存和星盘计算
- 长期记忆抽取和检索
- 后台训练资料上传
- GitHub 资料导入
- AI 训练成知识片段
- 训练对话流式输出
- 输出策略和模型编排
- Postgres + pgvector schema 草案
- Redis 限流、任务队列、对象存储抽象
- Docker / Caddy 部署配置

迁移原则：

1. 业务算法和纯函数优先直接搬。
2. 旧 `http.server` 路由不搬，改接 `life2` 的 FastAPI。
3. 旧 SQLite store 不整体搬，按 `life2` SQLAlchemy 模型重建。
4. 旧前端 UI 不整体搬，只参考交互和字段。
5. 旧测试用例要随模块一起迁，保证不是凭感觉复用。

## 可直接复用

### 文件上传与资料解析

来源：

- `astro_daily_agent/training_documents.py`
- `astro_daily_agent/tests/test_training_documents.py`

能力：

- 安全文件名清洗。
- 支持 `.docx`、`.pdf`、`.md`、`.markdown`、`.txt`、`.json`、`.yaml`、`.yml`。
- Markdown 按标题切分。
- 普通文本按段落和长度切分。
- DOCX 优先走占星结构化解析，失败后退回普通段落。

迁入阶段：第三期训练中心 2.0。

迁移方式：可直接复制为 `app/services/training_documents.py` 或拆进 `app/training/documents.py`，把返回的 `KnowledgeEntry` 适配成 `life2` 的 `KnowledgeSource` / `KnowledgeChunk`。

### GitHub 公开资料导入

来源：

- `astro_daily_agent/github_import.py`
- `astro_daily_agent/tests/test_github_import.py`

能力：

- 支持 GitHub repo、tree、blob、raw 链接。
- 递归发现目录内可支持资料文件。
- 限制文件数量和文件大小。
- 返回 upload pipeline 兼容结构。

迁入阶段：第三期训练中心 2.0。

迁移方式：核心函数可直接搬；把 `User-Agent` 改成 `Nexa-AI-Admin`，把错误类接到 FastAPI `HTTPException` 或服务层错误。

### AI 训练 JSON 解析和知识片段规范化

来源：

- `astro_daily_agent/training.py`
- `astro_daily_agent/tests/test_training.py`

能力：

- 训练 Agent 系统提示。
- 控制每批资料条数和 chunk 长度。
- 支持模型返回对象、数组、Markdown code fence、混杂文本中的 JSON。
- 训练输出 schema。
- 把训练结果规范成草稿知识片段，包含 tags、domain、status。

迁入阶段：第三期训练中心 2.0。

迁移方式：可直接复用 prompt、schema、`parse_training_response()`、`normalize_training_chunk()`。模型调用要改接 `life2` 现有 `call_model_provider()` 和输出校验器。

### OpenAI Responses 与 SSE 解析

来源：

- `astro_daily_agent/llm.py`
- `astro_daily_agent/tests/test_llm.py`

能力：

- Responses API payload 构造。
- 非流式文本解析。
- SSE `response.output_text.delta` 解析。
- 结构化 JSON 调用。
- 运行状态判断。

迁入阶段：第三期训练对话、第四期前台聊天。

迁移方式：`life2` 已有第一版 OpenAI adapter，但缺少 SSE。可直接迁 `stream_delta_from_event()`、`iter_openai_sse_text()` 和 stream request 逻辑，环境变量改成 `NEXA_*`。

### 回复策略

来源：

- `astro_daily_agent/response_policy.py`

能力：

- `free`、`standard`、`deep`、`risk` 四类输出策略。
- 根据关键词自动选择深度或风险策略。
- 控制最大字数、token、语气、结构、是否引用资料/知识/记忆。
- 流式输出长度截断。

迁入阶段：第四期前台聊天，部分可提前并入第五期模型路由 2.0。

迁移方式：直接迁策略定义和 `select_response_policy_key()`，与 `life2` 的 `OutputPolicy` 合并。后台控制台已有输出策略 UI，可以扩字段而不是重做。

### 长期记忆候选抽取

来源：

- `astro_daily_agent/memory.py`
- `astro_daily_agent/tests/test_memory.py`

能力：

- 从用户问题和回答中抽取偏好、近况、事业、关系、财富、情绪、安全边界等记忆候选。
- 生成检索 token。
- 对外 payload 隐藏内部 score。

迁入阶段：第四期用户记忆与前台聊天。

迁移方式：纯函数可以直接搬。存储层不要搬旧 SQLite，改用 `life2` 新的 `UserMemorySummary`、`MemoryItem` 等 SQLAlchemy 模型。

### 本命盘计算

来源：

- `astro_daily_agent/chart.py`

能力：

- 时区解析。
- 出生日期和时间校验。
- Swiss Ephemeris 星体落座。
- 有经纬度时计算宫位。
- 缺出生地时给 warnings，不硬编宫位。

迁入阶段：第四期前台聊天和用户资料。

迁移方式：可直接搬为独立服务。需要确认生产依赖 `pyswisseph` 和星历文件策略。

## 改造后复用

### 客户咨询编排

来源：

- `astro_daily_agent/agent.py`

已有能力：

- 问题分类。
- 读取本命资料、盘面、知识、历史、记忆。
- 调模型或本地模板。
- 保存咨询和记忆。
- 支持流式咨询。

不能原样搬的原因：

- 依赖旧 `AstroStore`。
- 当前用户固定 `local`。
- 和旧前台页面耦合。

迁入阶段：第四期。

迁移方式：保留流程和 prompt 结构，重写数据访问层，接 `life2` App API、用户表、记忆表、调用追踪和模型路由。

### 模型编排

来源：

- `astro_daily_agent/model_orchestration.py`

已有能力：

- 模型质量分。
- 成本档位。
- 路由策略 `cost_first`、`quality_first`、`balanced`。
- API key 来源和 endpoint 规范化。

`life2` 当前已有：

- `ModelConfig`
- `ModelProviderKey`
- `OutputPolicy`
- 路由预览
- OpenAI adapter

迁入阶段：第五期模型路由 2.0。

迁移方式：不要替换 `life2` 现有模型表；迁移选择算法和默认路由，把质量分、成本档位、策略字段补进现有模型配置。

### 后台训练对话和自动训练入库

来源：

- `astro_daily_agent/server.py`
- `astro_daily_agent/static/admin.js`

已有能力：

- 上传资料。
- GitHub 导入。
- 训练对话。
- SSE 流式训练对话。
- 识别“开始训练/入库/发布”等执行意图。
- 自动训练、审核、发布知识版本。

不能原样搬的原因：

- 旧路由基于 `BaseHTTPRequestHandler`。
- 旧 UI 和 `life2` 新控制台风格不一致。

迁入阶段：第三期训练中心 2.0。

迁移方式：服务函数和意图判断可以搬；FastAPI 路由、SQLAlchemy 模型、后台 UI 按 `life2` 重写。

### Postgres + pgvector schema

来源：

- `astro_daily_agent/scalable/postgres_schema.sql`
- `astro_daily_agent/tests/test_scalable_schema.py`

已有能力：

- tenants、users、sessions。
- birth profiles、chart snapshots、consultations。
- memory summaries、memory items with vector。
- knowledge sources、chunks、versions with vector。
- training runs。
- usage events、retrieval logs、task jobs。

迁入阶段：第二期生产化底座。

迁移方式：不能直接执行整份 SQL，因为 `life2` 已经有一套后台管理模型。建议把它改造成 Alembic migration，并将 `life2` 已有表映射到新 schema，避免两套重复表。

### 限流、任务队列、对象存储

来源：

- `astro_daily_agent/scalable/rate_limit.py`
- `astro_daily_agent/scalable/tasks.py`
- `astro_daily_agent/scalable/object_storage.py`

已有能力：

- 内存限流和 Redis 限流形态。
- `TaskEnvelope`。
- 内存队列和 Redis 队列形态。
- 本地对象存储和安全 object key。

迁入阶段：第二期生产化底座。

迁移方式：可以直接搬抽象和测试；生产实现接 Redis / RQ 或 Dramatiq。对象存储先保留 Local，后续替换 Vultr Object Storage / S3 / R2。

## 不建议复用

### 旧 HTTP 服务框架

来源：`astro_daily_agent/server.py` 的 `ThreadingHTTPServer` / `BaseHTTPRequestHandler` 部分。

原因：

- `life2` 已经使用 FastAPI。
- 旧路由手工解析 multipart、query、SSE，维护成本高。
- 继续沿用会造成两套服务框架混乱。

处理：只搬业务 helper，不搬 HTTP handler。

### 旧静态前端整体布局

来源：

- `astro_daily_agent/static/index.html`
- `astro_daily_agent/static/admin.html`
- `astro_daily_agent/static/app.js`
- `astro_daily_agent/static/admin.js`
- `astro_daily_agent/static/styles.css`

原因：

- `life2` 已经重做后台控制台。
- 旧 UI 和当前视觉体系不统一。
- 直接搬会造成样式冲突。

处理：只参考训练对话、拖拽上传、GitHub 导入、流式渲染的交互细节。

### 旧 SQLite Store 整体

来源：`astro_daily_agent/store.py`

原因：

- `life2` 已经使用 SQLAlchemy。
- 旧 store 是手写 sqlite3，直接搬会形成第二套数据访问层。

处理：只参考表结构和业务方法，按 `life2` 模型重写。

## 分期迁移清单

### 第二期：生产化底座

优先迁：

- `scalable/postgres_schema.sql` 的表设计思想。
- `scalable/rate_limit.py`
- `scalable/tasks.py`
- `scalable/object_storage.py`
- `scalable/settings.py`
- `scalable/migration.py`

需要新开发：

- `life2` Alembic 或等价迁移机制。
- SQLAlchemy 版 Postgres 模型。
- 本地 SQLite 到 Postgres 的正式迁移脚本。
- 后台任务运行器。
- 生产日志和部署配置整合。

### 第三期：训练中心 2.0

优先迁：

- `training_documents.py`
- `github_import.py`
- `training.py`
- `server.py` 中训练对话和自动训练入库 helper。
- 相关 tests。

需要新开发：

- `life2` 后台训练中心 UI。
- FastAPI 上传接口。
- 训练任务异步化。
- 知识版本审核/发布/回滚 UI。
- 训练失败重试和错误展示。

### 第四期：用户记忆和前台聊天

优先迁：

- `memory.py`
- `chart.py`
- `agent.py` 的编排流程。
- `llm.py` 的 SSE 流式输出。
- `response_policy.py`

需要新开发：

- 用户、出生资料、咨询、记忆 SQLAlchemy 模型。
- App 前台聊天接口。
- 流式 SSE API。
- 用户资料隐私删除/导出。
- 与后台 `CallTrace`、成本中心、模型路由打通。

### 第五期：模型路由和成本控制 2.0

优先迁：

- `model_orchestration.py` 的选择算法。
- `response_policy.py` 的策略选择。
- `scalable/model_router.py` 的意图路由和成本估算。

需要新开发：

- `life2` 模型配置字段升级。
- 成本预算、限流、告警。
- A/B 测试。
- 模型失败重试和备用模型切换。

### 第六期：商业化

旧项目基本没有完整支付和权益体系。

需要新开发：

- 套餐、订单、支付回调。
- 免费额度。
- 深度解读权益。
- 付费报告生成和查询。
- 运营漏斗和留存数据。

## 推荐下一步

下一步先做第二期，但不是从零做。

第一批应该迁入：

1. `scalable/settings.py`
2. `scalable/object_storage.py`
3. `scalable/tasks.py`
4. `scalable/rate_limit.py`
5. `training_documents.py`
6. `github_import.py`

原因：

- 它们最独立，和旧 UI/旧 store 耦合低。
- 已有测试。
- 对第二期和第三期都马上有用。

第一批不要先迁：

- `server.py` 整体。
- `store.py` 整体。
- 旧 `static/` 整体。

这些会把旧架构带进新项目，后面会乱。
