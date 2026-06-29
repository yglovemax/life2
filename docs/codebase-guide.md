# Codebase Guide

日期：2026-06-18

这份文档说明代码放在哪里、主要职责是什么、测试怎么看。改代码前先读这里，避免功能散乱。

## 顶层结构

```text
app/
  main.py                 FastAPI 入口和 HTTP 路由
  agent.py                通用占卜 Agent V1 编排：占术路由、入口上下文、工具协议和 Agent 回复包装
  services.py             主要业务逻辑和编排
  models.py               SQLAlchemy 模型
  db.py                   数据库引擎、Session、schema 初始化、运行状态
  seed.py                 默认页面、模块、模型、管理员种子数据
  worker.py               队列 worker 入口
  core/settings.py        环境变量和运行配置
  platform/               对象存储、任务队列、限流、运行时工厂
  training/               训练资料解析、AI 训练输出规范、GitHub 导入
  static/                 后台管理 MVP 静态页面
alembic/
  versions/               数据库迁移
docs/                     产品、架构、接口、运维、安全文档
tests/                    API、服务、平台底座测试
```

## 入口和路由

`app/main.py` 负责：

- 启动时初始化数据库和种子数据。
- 挂载 `/admin` 静态后台页面。
- 提供 `/api/*` 路由。
- 处理 App Token、后台管理员 Token、SSE Token。
- 给路由层做轻量错误转换，核心业务交给 `app/services.py`。

主要路由分组：

- 基础：`/api/health`、`/api/runtime/status`
- 后台登录：`/api/auth/*`
- App 正式接口：`/api/app/*`
- App Agent 接口：`/api/app/agent/*`
- 模块管理：`/api/modules/*`
- 知识库：`/api/knowledge-*`、`/api/knowledge/*`
- 算法库：`/api/algorithms/*`
- 训练：`/api/training/*`
- embedding：`/api/embeddings/rebuild`
- 测试和追踪：`/api/test-runs/*`、`/api/call-traces/*`
- 问题追踪：`/api/issues/*`
- 模型配置：`/api/model-provider-keys/*`、`/api/model-router/preview`
- 输出策略：`/api/output-policies/*`
- 成本、告警、指标：`/api/costs/summary`、`/api/fallback-alerts`、`/api/metrics`
- 安全：`/api/security/*`

## 业务服务

`app/services.py` 当前承载主要业务。后续如果拆分，建议按这些领域拆：

- 模块和发布：`list_modules`、`get_module_detail`、`create_module`、`update_module`、`publish_module`、`rollback_module`
- 模型调用和输出校验：`run_module_trace`、`resolve_model_response`、`validate_model_output`
- 知识库：`create_knowledge_source`、`upload_knowledge_files`、`import_github_knowledge_sources`、`search_knowledge`
- 算法库：`create_algorithm`、`upload_algorithm_files`、`publish_algorithm`、`run_algorithm_test`、`execute_algorithm`
- 训练：`create_training_run`、`execute_training_run_job`、`retry_training_run`、`publish_training_run`
- embedding：`build_text_embedding_payload`、`apply_text_embedding`、`create_embedding_rebuild_job`、`execute_embedding_rebuild_job`
- App 用户和盘面：`create_or_update_app_user`、`save_birth_profile`、`get_user_chart`、`calculate_user_chart`
- 聊天和记忆：`create_chat_session`、`generate_chat_reply`、`create_memory_item`、`execute_memory_summary_job`
- Agent 编排：`app/agent.py` 复用聊天和记忆服务，负责占术路由、确认按钮、工具调用协议、推荐包装
- 安全：`login_admin`、`authenticate_admin_token`、`create_app_api_key`、`authenticate_app_token`
- 模型 Key 和输出策略：`create_model_provider_key`、`revoke_model_provider_key`、`create_output_policy`、`preview_model_route`
- 指标和审计：`metrics`、`cost_summary`、`list_audit_events`

## 数据模型

`app/models.py` 主要模型分组：

- 模块管理：`Page`、`Module`、`PromptTemplate`、`FieldContract`、`ModuleVersion`
- 模型和输出：`ModelConfig`、`ModelProviderKey`、`OutputPolicy`
- 调用追踪：`CallTrace`、`Issue`
- 知识和训练：`KnowledgeSource`、`KnowledgeChunk`、`TrainingRun`、`TrainingDraftChunk`
- 算法库：`AlgorithmDefinition`、`AlgorithmVersion`、`AlgorithmRun`
- App 用户：`AppUser`、`BirthProfile`
- 聊天和记忆：`ChatSession`、`ChatMessage`、`UserMemorySummary`、`MemoryItem`
- 安全：`AppApiKey`、`AuditEvent`、`AdminUser`、`AdminSession`

新增表时要同步：

- `app/models.py`
- Alembic migration
- 必要的序列化函数
- 文档和测试

## 平台底座

`app/platform/`：

- `object_storage.py`：本地对象存储和对象 key 安全处理。
- `tasks.py`：`TaskEnvelope`、内存队列、Redis 队列、单任务消费。
- `rate_limit.py`：内存限流、Redis 限流。
- `runtime.py`：按环境变量创建对象存储、队列、限流、Redis client。

当前可配置项：

- `NEXA_OBJECT_STORAGE_BACKEND`
- `NEXA_TASK_QUEUE_BACKEND`
- `NEXA_RATE_LIMIT_BACKEND`
- `NEXA_REDIS_URL`

## Worker

`app/worker.py` 消费任务队列。

当前任务类型：

- `training.run`：执行 AI 训练运行。
- `memory.summarize`：更新用户长期记忆摘要。
- `embedding.rebuild`：重建知识片段和用户记忆 embedding。

本地 memory 队列只适合同进程调试。生产 API 和 worker 分进程时要用 Redis。

## 训练子系统

`app/training/`：

- `documents.py`：解析上传文件，转训练 entries 和 markdown。
- `ai.py`：训练系统提示、输出 schema、训练响应解析和归一化。
- `github_import.py`：从 GitHub 拉取资料文件用于训练入库。

训练流程：

```text
上传/导入资料 -> parse entries -> AI 结构化草稿 -> TrainingDraftChunk -> publish -> KnowledgeSource/KnowledgeChunk
```

## 后台静态页面

`app/static/`：

- `admin.html`
- `admin.js`
- `styles.css`

这是管理后台 MVP。新增核心后端能力时，优先保证 API 和文档稳定；后台 UI 可以后续迭代。

## 测试地图

- `test_admin_api.py`：后台模块、知识库、发布、模型、成本、安全等主 API。
- `test_app_user_backend_api.py`：App 用户、本命资料、盘面、聊天基础、记忆基础。
- `test_chat_reply_api.py`：聊天回复、上下文、模型调用、流式输出。
- `test_agent_api.py`：Agent 会话、占术路由、确认按钮、工具调用协议和回复包装。
- `test_auto_memory_extraction.py`：自动记忆抽取和摘要。
- `test_training_ingestion.py`：训练资料解析和知识检索。
- `test_training_runs_api.py`：AI 训练运行、发布、失败、重试、取消、队列。
- `test_embedding_rebuild_api.py`：embedding 同步/队列重建。
- `test_algorithm_registry_api.py`：算法库创建、上传、测试、发布和正式执行。
- `test_platform_primitives.py`：对象存储、队列、限流、Redis 工厂、OpenAI embedding provider。

## 新增功能落点规则

- 给 App 前端用的接口：放 `/api/app/*`，更新 `frontend-api-contract.md` 和 `app-api.md`。
- Agent 相关接口：放 `/api/app/agent/*`，业务逻辑优先放 `app/agent.py`，不要把占术路由规则塞进旧聊天函数里。
- 给后台管理用的接口：放对应管理分组，更新 `backend-integration.md`。
- 新增长期运行任务：使用 `TaskEnvelope`，在 `worker.py` 注册 handler。
- 新增配置：放 `app/core/settings.py`，文档写 README 和相关专题文档。
- 新增数据库字段：写 Alembic migration，并补测试。
- 新增外部服务调用：默认必须有 mock/fallback 路径，避免本地开发强依赖外网。
- 不要把新项目功能写回旧仓库；`life2` 是独立项目。
