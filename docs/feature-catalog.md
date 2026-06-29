# Feature Catalog

日期：2026-06-18

状态说明：

- `done`：已实现并有测试覆盖。
- `partial`：已有后端骨架或 MVP，但仍需生产级增强。
- `planned`：已确认方向，尚未实现。

## 后台管理

| 功能 | 状态 | 主要入口 | 说明 |
| --- | --- | --- | --- |
| 后台登录 | done | `/api/auth/login` | 默认本地账号 `admin / admin123`，生产必须用环境变量覆盖 |
| 管理员会话 | done | `/api/auth/me`, `/api/auth/logout` | 敏感接口使用 Bearer token |
| 模块中心 | done | `/api/modules` | 列出页面模块、状态、模型、调用和问题 |
| 模块详情 | done | `/api/modules/{module_id}` | Prompt、字段契约、调用记录、问题 |
| 模块编辑 | done | `PUT /api/modules/{module_id}` | 更新模块、Prompt、字段契约、模型、策略 |
| 发布回滚 | done | `/publish`, `/rollback`, `/versions` | 模块版本快照、灰度、上线、回滚 |
| 测试中心 | done | `/api/modules/{module_id}/test-run`, `/api/test-runs/batch` | 单模块测试和批量测试 |
| 人工评分 | done | `PUT /api/call-traces/{trace_id}/score` | 对模型输出打分 |
| 问题追踪 | done | `/api/issues`, `/api/modules/{module_id}/issues` | 问题创建、分配、状态推进 |
| 成本中心 | done | `/api/costs/summary` | 基于调用估算成本 |
| Fallback 告警 | done | `/api/fallback-alerts` | 查看 fallback 相关异常 |
| 指标 | done | `/api/metrics` | 总览指标 |

## 模型、路由和输出编排

| 功能 | 状态 | 主要入口 | 说明 |
| --- | --- | --- | --- |
| 模型配置 | done | `/api/models` | 种子模型、质量层级、成本 |
| 模型供应商 Key | done | `/api/model-provider-keys` | 只保存 hash 和前缀，不保存明文 |
| 模型路由预览 | done | `/api/model-router/preview` | 根据模块、质量、策略预览模型选择 |
| 输出策略 | done | `/api/output-policies` | token、温度、fallback、安全边界 |
| mock 模型调用 | done | `NEXA_MODEL_CALL_MODE=mock` | 本地默认，不出网 |
| OpenAI Responses 调用 | done | `NEXA_MODEL_CALL_MODE=live` | 使用运行时 `NEXA_OPENAI_API_KEY` |
| JSON 字段契约校验 | done | `run_module_trace` | 非合法 JSON 或缺字段进入 fallback |

## 知识库和训练

| 功能 | 状态 | 主要入口 | 说明 |
| --- | --- | --- | --- |
| 手动知识录入 | done | `/api/knowledge-sources`, `/api/knowledge-entries` | markdown 切分入库 |
| 文件上传训练资料 | done | `/api/knowledge/uploads` | 支持上传解析后入知识源 |
| GitHub 导入资料 | done | `/api/knowledge/github-import` | 从 GitHub 拉资料入库 |
| 知识 chunk 查询 | done | `/api/knowledge-chunks` | 可按 `source_id`、tag 查询 |
| 知识搜索 | done | `/api/knowledge/search` | 关键词/tag + embedding 相似度 |
| 知识分类 | done | `/api/knowledge/taxonomy` | 占星、八字等维度建议 |
| AI 训练运行 | done | `/api/training/runs` | 同步或队列生成草稿 chunks |
| 训练质检报告 | done | `/api/training/runs/{run_id}/quality-report` | 发布前检查阻断项、警告和置信度 |
| 训练质检审计 | done | `quality_events`, `/api/security/audit-events` | 记录通过、阻断和 override 发布 |
| 训练发布 | done | `/api/training/runs/{run_id}/publish` | 草稿发布为正式知识源 |
| 训练失败重试 | done | `/api/training/runs/{run_id}/retry` | 支持更新 payload 后重试 |
| 训练取消 | done | `/api/training/runs/{run_id}/cancel` | 队列中任务可取消 |
| 训练队列状态 | done | `/api/training/queue-status` | 队列、状态计数、排队 run ids |
| 资料归档/恢复/删除 | done | `/api/knowledge-sources/{source_id}/archive`, `/restore`, `DELETE` | 归档不进检索；硬删除只允许未被训练运行引用的资料 |
| 重复资料提示 | done | `/api/knowledge-sources` | 创建资料时返回 `duplicate` 元信息 |
| 重复资料合并 | done | `/api/knowledge/duplicates`, `/api/knowledge-sources/{source_id}/merge` | 查重复组；合并后重复源归档并写审计 |
| 知识清理建议 | done | `/api/knowledge/cleanup-recommendations` | 只读建议清单，提示可合并/可删除项 |
| 知识清理执行 | done | `/api/knowledge/cleanup-recommendations/execute` | 批量执行有效建议并写审计 |
| 算法库 | done | `/api/algorithms`, `/api/algorithms/uploads` | JSON rule_spec 算法草稿、上传、测试、发布、正式执行和运行记录 |

## App 用户、盘面和聊天

| 功能 | 状态 | 主要入口 | 说明 |
| --- | --- | --- | --- |
| 通用占卜 Agent V1 | partial | `/api/app/agent/*` | Phase A/B/C/D 已实现 Agent 会话、占术路由预览、入口上下文、确认按钮、回复包装、工具注册表、工具执行协议、Agent SSE、反馈和记忆控制；真实工具 provider 后续继续 |
| App Token 鉴权 | done | `/api/app/*` | 支持 Bearer 和 `X-Nexa-Api-Key` |
| 用户创建/更新 | done | `POST /api/app/users` | `external_id` 幂等 |
| 本命资料保存 | done | `PUT /api/app/users/{user_id}/birth-profile` | 支持占星、八字、hybrid |
| 盘面快照读取 | done | `GET /api/app/users/{user_id}/chart` | 返回 birth profile 和 snapshot |
| 盘面计算/回写 | done | `POST /api/app/users/{user_id}/chart/calculate` | mock/外部 HTTP 占位 |
| 页面渲染 | done | `/api/app/pages/{page_slug}/render` | 只渲染 gray/live 模块 |
| 模块渲染 | done | `/api/app/modules/{module_slug}/render` | 返回正式 JSON 和 trace id |
| 聊天会话 | done | `/api/app/chat/sessions` | 创建和查询会话 |
| 聊天消息 | done | `/api/app/chat/sessions/{session_id}/messages` | 手动写入消息 |
| 同步聊天回复 | done | `/api/app/chat/sessions/{session_id}/reply` | 自动写 trace、记忆和上下文 |
| SSE 流式聊天 | done | `/api/app/chat/sessions/{session_id}/stream` | 支持 header 或 `api_key` |
| 聊天限流 | done | `X-RateLimit-*` | memory/Redis 后端 |

## 长期记忆

| 功能 | 状态 | 主要入口 | 说明 |
| --- | --- | --- | --- |
| 记忆摘要写入 | done | `PUT /api/app/users/{user_id}/memory-summary` | 可手动更新 |
| 记忆条目写入 | done | `POST /api/app/users/{user_id}/memories` | 创建时写 embedding |
| 用户记忆查询 | done | `GET /api/app/users/{user_id}/memories` | 返回摘要和条目 |
| 用户记忆删除 | done | `DELETE /api/app/users/{user_id}/memories/{memory_id}` | 软删除，列表只返回 active |
| 用户记忆设置 | done | `GET/PUT /api/app/users/{user_id}/memory-settings` | 控制记忆沉淀与个性化使用 |
| 自动记忆抽取 | done | 聊天 reply/stream | 从用户话术和回答中抽取偏好/关系等 |
| 记忆摘要异步 | done | `memory.summarize` | worker 任务 |
| 大规模用户记忆策略 | partial | 文档已定 | 仍需接 Postgres/pgvector、缓存、分片策略 |

## 八字能力

| 功能 | 状态 | 主要入口 | 说明 |
| --- | --- | --- | --- |
| 八字本命页面 | done | `bazi-birth-reading` | 种子页面和模块 |
| 八字日运页面 | done | `bazi-daily-reading` | 自动注入日期和日运上下文 |
| 八字资料保存 | done | birth profile | 保存四柱、日主、五行、十神等输入快照 |
| 八字事实注入 | done | render app page/module | 自动注入 `bazi_facts`、`pillars`、`day_master` |
| 八字算法 HTTP 占位 | partial | `NEXA_BAZI_CALC_MODE=live` | 真实算法服务待接入 |
| 八字规则算法库 | partial | `/api/algorithms` | 已支持 JSON 规则算法；后续需补完整排盘、大运、流年算法规则 |
| 大运/流年完整计算 | planned | 未实现 | 需要外部算法或本地排盘引擎 |

## 生产底座

| 功能 | 状态 | 主要入口 | 说明 |
| --- | --- | --- | --- |
| Alembic 迁移 | done | `alembic upgrade head` | SQLite 本地、Postgres 生产 |
| 数据库运行时切换 | done | `NEXA_DATABASE_URL` | 支持切换 URL |
| Postgres/pgvector 迁移 | done | migration `20260617_0002` | vector 列和 ivfflat 索引迁移已准备 |
| 对象存储工厂 | done | `NEXA_OBJECT_STORAGE_BACKEND` | 当前 local |
| 任务队列工厂 | done | `NEXA_TASK_QUEUE_BACKEND` | memory/Redis |
| 限流工厂 | done | `NEXA_RATE_LIMIT_BACKEND` | memory/Redis |
| Redis client 复用 | done | `NEXA_REDIS_URL` | 队列和限流复用 |
| Redis 运行状态检查 | done | `/api/runtime/status` | 展示 Redis 连通、队列后端、积压任务数 |
| worker | done | `python -m app.worker` | 消费训练、记忆、embedding 任务 |
| mock embedding | done | 默认 | 无密钥开发和测试 |
| OpenAI embedding | done | `NEXA_EMBEDDING_PROVIDER=openai` | 调用 `/embeddings`，失败 fallback mock |
| embedding 批量重建 | done | `/api/embeddings/rebuild` | sync/queued，knowledge/memory/all |
| pgvector ANN 检索 | partial | PostgreSQL + OpenAI vector | PG 下优先使用 `<=>` 向量排序；真实效果需服务器验证 |
| 真实 Redis 冒烟 | planned | 服务器环境 | 需要部署 Redis 后验证 API/worker 分进程共享队列 |

## 安全和审计

| 功能 | 状态 | 主要入口 | 说明 |
| --- | --- | --- | --- |
| 后台敏感接口保护 | done | `require_admin_session` | Key、策略、安全审计接口已保护 |
| App Key 管理 | done | `/api/security/app-keys` | 创建、撤销、脱敏 |
| 安全状态 | done | `/api/security/status` | 检查默认 token 等风险 |
| 审计事件 | done | `/api/security/audit-events` | 登录、鉴权失败、key 操作、渲染等 |
| 生产密码策略 | partial | 环境变量 | 仍需接更完整后台权限体系 |

## 尚未开始或最后阶段

| 功能 | 状态 | 说明 |
| --- | --- | --- |
| 收费、会员、套餐 | planned | 用户明确要求最后做 |
| 订单、支付、发票 | planned | 依赖收费方案 |
| 多租户组织隔离 | planned | 10 万用户规模后需要 |
| 管理后台最终 UI | partial | 当前是 MVP，后续可独立设计 |
| 客户端聊天 UI | 外部团队负责 | 本仓库维护后端合同 |
