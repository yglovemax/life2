# Backend Integration Contract

日期：2026-06-16

## 项目边界

`life2` 后续按后端平台推进，不负责客户侧前端 UI。

后端负责：

- AI API 管理后台。
- Prompt、字段契约、Fallback、发布流。
- 知识库、训练资料、AI 训练草稿和发布。
- 模型供应商配置、模型路由、输出策略。
- App Key 鉴权、审计、调用追踪。
- 未来用户资料、本命盘、聊天记录、长期记忆、成本和权益。

前端团队负责：

- 客户侧页面和交互。
- 客户聊天 UI。
- 本命资料表单和展示。
- 深度解读、免费引流、付费入口的视觉和交互。

双方通过 HTTP JSON API 和未来 SSE 流式 API 集成。

## 当前可用基础接口

健康检查：

```http
GET /api/health
```

后台登录：

```http
POST /api/auth/login
GET /api/auth/me
POST /api/auth/logout
```

App 调用：

```http
POST /api/app/modules/{module_slug}/render
POST /api/app/pages/{page_slug}/render
```

请求头：

```http
Authorization: Bearer <app_api_key>
```

也支持：

```http
X-Nexa-API-Key: <app_api_key>
```

## 知识库接口

Markdown / 手工知识：

```http
POST /api/knowledge-sources
POST /api/knowledge-entries
GET /api/knowledge-sources
GET /api/knowledge-chunks
POST /api/knowledge/search
```

训练资料上传：

```http
POST /api/knowledge/uploads
```

示例：

```json
{
  "tags": ["占星", "训练资料"],
  "files": [
    {
      "filename": "moon.md",
      "content_type": "text/markdown",
      "content_base64": "IyDmnIjkuq4K5pyI5Lqu5Luj6KGo5oOF57uq5a6J5YWo5oSf44CC"
    }
  ]
}
```

GitHub 导入：

```http
POST /api/knowledge/github-import
```

示例：

```json
{
  "url": "https://github.com/org/repo/tree/main/docs",
  "tags": ["GitHub", "占星"]
}
```

## AI 训练运行接口

创建训练运行：

```http
POST /api/training/runs
```

从已有资料源训练：

```json
{
  "source_id": 12,
  "tags": ["占星", "训练测试"]
}
```

直接传入临时内容训练：

```json
{
  "title": "月亮资料",
  "content": "# 月亮\n月亮代表情绪安全感。",
  "tags": ["月亮"]
}
```

开发/测试时可传入模拟模型输出：

```json
{
  "source_id": 12,
  "simulate_model_response": {
    "chunks": [
      {
        "title": "月亮情绪安全感",
        "body": "月亮相关内容适合用于解释用户的情绪需求和安全感来源。",
        "domain": "astrology",
        "tags": ["月亮", "情绪"],
        "rule_type": "interpretation",
        "use_when": "用户询问情绪、亲密关系和安全感时",
        "avoid_when": "不要断言对方一定会怎样",
        "examples": ["可以说：你更需要被稳定回应。"],
        "confidence": 0.88
      }
    ]
  }
}
```

返回状态：

- `completed`：已生成训练草稿。
- `failed`：模型输出或调用失败，错误写入 `error`。
- `published`：训练草稿已发布成正式知识源。

列表和详情：

```http
GET /api/training/runs
GET /api/training/runs/{run_id}
```

发布训练草稿：

```http
POST /api/training/runs/{run_id}/publish
```

示例：

```json
{
  "title": "AI 训练发布：月亮规则",
  "tags": ["已发布"]
}
```

发布后会创建 `source_type=ai_training` 的正式知识源，并进入 `/api/knowledge/search` 检索环境。

## 用户资料、本命资料、聊天和记忆接口

以下接口已实现，均使用 App Key 鉴权。

创建或更新用户：

```http
POST /api/app/users
```

`external_id` 是幂等键，前端可传微信 openid、App 用户 ID 或业务用户 ID。

```json
{
  "external_id": "wechat-openid-123",
  "nickname": "max",
  "locale": "zh-CN",
  "timezone": "Asia/Shanghai",
  "profile": {
    "channel": "wechat"
  }
}
```

查询用户：

```http
GET /api/app/users/{user_id}
```

保存本命资料：

```http
PUT /api/app/users/{user_id}/birth-profile
```

```json
{
  "nickname": "max",
  "birth_date": "1989-09-29",
  "birth_time": "16:00",
  "birth_city": "兰州",
  "birth_country": "CN",
  "birth_timezone": "Asia/Shanghai",
  "latitude": "36.0611",
  "longitude": "103.8343"
}
```

获取基础盘面快照：

```http
GET /api/app/users/{user_id}/chart
```

当前返回 `calculation_level=sun_sign_only`，只保证太阳星座和本命资料快照。完整宫位、上升、相位会在星盘计算服务阶段接入。

创建聊天会话：

```http
POST /api/app/chat/sessions
```

```json
{
  "user_id": 1,
  "title": "今日咨询",
  "topic": "daily",
  "metadata": {
    "client": "web"
  }
}
```

查询聊天会话和消息：

```http
GET /api/app/chat/sessions/{session_id}
```

追加聊天消息：

```http
POST /api/app/chat/sessions/{session_id}/messages
```

```json
{
  "role": "user",
  "content": "今天适合推进合作吗？"
}
```

`role` 支持 `user`、`assistant`、`system`、`tool`。

保存长期记忆摘要：

```http
PUT /api/app/users/{user_id}/memory-summary
```

```json
{
  "summary": "用户偏好清晰直接的建议，关注合作和关系边界。"
}
```

新增可检索记忆条目：

```http
POST /api/app/users/{user_id}/memories
```

```json
{
  "memory_type": "preference",
  "content": "用户喜欢先给结论再解释。",
  "tags": ["偏好", "表达"],
  "importance": 4
}
```

查询用户记忆：

```http
GET /api/app/users/{user_id}/memories
```

## 后续待定接口

尚未实现：

- `GET /api/app/chat/sessions/{session_id}/stream`
- 聊天模型编排和流式回复。
- 自动记忆抽取。
- 完整星盘计算服务。
- 用户级额度、计费和权益。
