# Nexa AI API Admin Architecture

## 目标

本项目按需求原文实现 Nexa 占卜 APP 的 AI API 管理后台。后台不是训练大模型权重，而是管理 AI 内容生产链路：

`页面 -> 模块 -> Prompt -> 算法数据 -> 知识库 -> 模型调用 -> JSON 字段契约 -> 测试追踪 -> 问题追踪 -> 发布回滚`

## 一期边界

一期先接入两个页面：

- 出生星盘解读页
- 每日星座运势页

页面按模块拆分，每个模块独立管理 Prompt、模型、字段契约、测试、Fallback、版本和问题追踪。

## 当前代码结构

```text
app/
  main.py              FastAPI 入口、路由、静态后台页面
  db.py                数据库连接和初始化
  models.py            核心数据库模型
  seed.py              一期页面和模块预置数据
  services.py          模块中心、详情、测试追踪、指标服务
  static/              第一版后台前端
docs/
  requirements/        原版需求文档归档
tests/
  test_admin_api.py    第一批 API 行为测试
```

## 核心模型

- `Page`：用户端页面。
- `Module`：页面模块，是后台管理和发布的最小单元。
- `PromptTemplate`：五段式 Prompt。
- `FieldContract`：输出 JSON 字段契约。
- `ModelConfig`：模型供应商、模型名、质量层级和成本配置。
- `CallTrace`：一次测试或正式调用的输入、模型请求、原始返回、最终 JSON 和成本。
- `ModuleVersion`：模块版本快照。
- `Issue`：问题类型、负责人和处理状态。

## 第一版调用链路

1. 后台启动时初始化 SQLite 数据库。
2. 种子数据创建两个页面和 31 个一期模块。
3. 模块中心读取模块列表、负责人、模型、状态、调用量、Fallback 数。
4. 模块详情展示 Prompt 五段式、字段契约、最近调用记录和当前问题。
5. 单模块测试接口生成一次模拟模型调用，保存 `CallTrace`。
6. 发现内容、字段、Fallback、模型或算法数据问题后，绑定到模块生成 `Issue`。
7. 问题可以分配负责人，并从 `open` 推进到 `in_progress` 或 `resolved`。
8. 前端刷新详情区，展示最终 JSON、问题状态和未解决问题数。

## 后续演进

- 接入真实模型调用和模型路由器。
- 增加更完整的发布审批。
- 增加问题操作审计和评论历史。
- 从 SQLite 平滑切换到 Postgres。
