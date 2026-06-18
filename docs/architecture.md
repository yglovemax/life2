# Nexa AI API Admin Architecture

日期：2026-06-18

## 目标

本项目按需求原文实现 Nexa 占卜 APP 的 AI API 管理后台。后台不是训练大模型权重，而是管理 AI 内容生产链路：

```text
页面 -> 模块 -> Prompt -> 算法数据 -> 知识库 -> 模型路由 -> 输出编排
-> 模型供应商适配 -> JSON 字段契约校验 -> Fallback
-> 测试追踪 -> 问题追踪 -> 发布回滚 -> App 正式输出
```

平台学习流程是：

```text
资料上传/导入 -> 结构化切分 -> AI 训练草稿 -> 人工发布 -> 检索使用
```

## 产品边界

一期最初接入：

- 出生星盘解读页
- 每日星座运势页

当前已经扩展到：

- 八字本命解读页
- 八字日运页
- 客户聊天和长期记忆
- 训练资料上传、GitHub 导入、AI 训练发布
- 模型路由、输出策略、供应商 Key 管理
- 生产化底座：迁移、worker、队列、限流、embedding

页面按模块拆分，每个模块独立管理 Prompt、模型、输出策略、字段契约、测试、Fallback、版本和问题追踪。客户侧 App 只读取 `gray` 或 `live` 状态模块。

## 当前代码结构

```text
app/
  main.py              FastAPI 入口、路由、静态后台页面
  db.py                数据库连接、Session、schema 初始化、运行状态
  models.py            核心数据库模型
  seed.py              页面、模块、模型、管理员种子数据
  services.py          主要业务逻辑和编排
  worker.py            队列 worker 入口
  core/settings.py     环境变量配置
  platform/            对象存储、任务队列、限流和 Redis 运行时工厂
  training/            上传资料解析、训练输出 schema、GitHub 导入
  static/              第一版后台前端
alembic/
  versions/            数据库迁移
docs/
  README.md            文档总目录
  project-memory.md    当前项目记忆和关键决策
  codebase-guide.md    代码地图
  feature-catalog.md   功能清单
  requirements/        原版需求文档归档
tests/
  test_*.py            API、训练、聊天、记忆、平台底座测试
```

更细的代码说明见 `codebase-guide.md`。

## 核心模型

- `Page`：用户端页面。
- `Module`：页面模块，是后台管理和发布的最小单元。
- `PromptTemplate`：五段式 Prompt。
- `FieldContract`：输出 JSON 字段契约。
- `ModelConfig`：模型供应商、模型名、质量层级和成本配置。
- `ModelProviderKey`：模型供应商 Key 的哈希和前缀，不保存明文。
- `OutputPolicy`：模型路由、备用模型、输出 token、温度、返回格式和安全边界。
- `CallTrace`：一次测试或正式调用的输入、模型请求、模型原始返回、最终 JSON、Fallback 原因和成本。
- `ModuleVersion`：模块版本快照。
- `Issue`：问题类型、负责人和处理状态。
- `KnowledgeSource`、`KnowledgeChunk`：知识资料和知识切片。
- `TrainingRun`、`TrainingDraftChunk`：AI 训练运行和草稿知识块。
- `AppUser`、`BirthProfile`：客户端用户、出生资料、本命资料和盘面快照。
- `ChatSession`、`ChatMessage`：聊天会话和消息。
- `UserMemorySummary`、`MemoryItem`：长期记忆摘要和可检索记忆条目。
- `AppApiKey`：托管 App Key 哈希和前缀。
- `AuditEvent`：安全和高风险动作审计。
- `AdminUser`、`AdminSession`：后台登录和管理员会话。

## 当前调用链路

1. 后台启动时初始化数据库。
2. 种子数据创建占星、日运、八字页面和模块。
3. 模块中心读取模块列表、负责人、模型、状态、调用量、Fallback 数。
4. 模块详情展示 Prompt 五段式、字段契约、最近调用记录和当前问题。
5. 模型路由根据输出策略选择主模型和备用模型。
6. 输出编排器提供最大输出 token、温度、返回格式和安全边界。
7. 默认 mock 模式生成模拟模型返回；live 模式通过 OpenAI Responses API 适配层请求真实模型。
8. 输出校验器解析模型原始返回，要求合法 JSON，并检查 AI 生成的必填字段。
9. 如果模型返回不是合法 JSON、缺少必填字段、供应商不可用或未配置运行时 Key，调用自动进入 Fallback。
10. 单模块测试接口保存 `CallTrace`，包含模型请求、原始响应、最终 JSON、Fallback 原因和成本估算。
11. App 正式渲染接口只读取发布状态模块，并写入 `request_type=official` 的调用追踪。
12. 聊天接口组合本命资料、盘面快照、知识命中、长期记忆和最近对话，再生成同步或 SSE 回复。
13. 聊天回复后自动抽取长期记忆，可同步更新摘要，也可交给 `memory.summarize` 队列任务。
14. 训练资料通过上传或 GitHub 导入进入知识库，AI 训练运行生成草稿，发布后进入检索环境。
15. worker 可异步消费训练、长期记忆摘要和 embedding 重建任务。

## 运行时组件

- 数据库：本地默认 SQLite，生产计划 Postgres。
- 迁移：Alembic。
- 对象存储：本地存储第一版，后续可替换云对象存储。
- 队列：本地 memory，生产需要 Redis。
- 限流：本地 memory，生产可 Redis。
- embedding：默认 mock，可配置 OpenAI provider。
- pgvector：迁移已准备，ANN 查询后续接入。

## 模型调用模式

默认模式是 `mock`，本地测试不会向外部模型供应商发起请求。

```bash
NEXA_MODEL_CALL_MODE=mock
```

生产开启真实模型调用：

```bash
NEXA_MODEL_CALL_MODE=live
NEXA_OPENAI_API_KEY=<openai_api_key>
```

当前代码保留平台侧二次校验，即使供应商返回异常，也会进入可追踪 Fallback。

## 后续演进

- 接真实 Redis，完成 API/worker 分进程队列验证。
- 接 Postgres + pgvector，启用真实向量列和 ANN 检索。
- 拆分 `app/services.py`，按领域形成更清晰的服务边界。
- 接真实八字排盘服务，补大运、流年、旺衰等结构。
- 增加更完整的发布审批、问题评论和操作历史。
- 收费、会员、订单、支付最后实现。
