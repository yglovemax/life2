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

八字接入第一版也走同一个接口，补充：

```json
{
  "chart_system": "bazi",
  "bazi_profile": {
    "year_pillar": "己巳",
    "month_pillar": "癸酉",
    "day_pillar": "乙丑",
    "hour_pillar": "甲申",
    "day_master": "乙木"
  }
}
```

获取基础盘面快照：

```http
GET /api/app/users/{user_id}/chart
```

当前返回支持三类基础快照：

- `system_type=astrology` → `calculation_level=sun_sign_only`
- `system_type=bazi` → `calculation_level=bazi_input_only`
- `system_type=hybrid` → `calculation_level=hybrid_foundation`

说明：

- 占星仍是太阳星座基础快照。
- 八字当前先接“输入型四柱事实”，方便和现有八字算法服务或人工录入结果对接。
- 完整宫位、上升、相位，以及八字大运、流年、藏干、旺衰，后续由独立计算服务补齐。

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

生成聊天回复：

```http
POST /api/app/chat/sessions/{session_id}/reply
```

请求示例：

```json
{
  "content": "今天适合推进合作吗？",
  "quality_tier": "standard",
  "knowledge_tags": ["合作"],
  "knowledge_limit": 5,
  "memory_extraction": true,
  "memory_run_mode": "sync"
}
```

开发联调时可传：

```json
{
  "content": "今天适合推进合作吗？",
  "simulate_model_response": "可以推进，但先确认节奏、边界和对方反馈。"
}
```

行为：

- 自动保存本轮 `user` 消息。
- 组装用户资料、基础盘面快照、长期记忆、最近消息、知识库命中。
- 默认 mock 模式下返回可用回复。
- `NEXA_MODEL_CALL_MODE=live` 或传 `use_live_model=true` 时调用 OpenAI Responses API。
- 自动保存 `assistant` 消息。
- 默认自动抽取长期记忆，写入 `memory_items` 并更新 `memory_summary`。
- `memory_run_mode=queued` 时，只同步写入 `memory_items`，把 `memory_summary` 更新放入 `memory.summarize` 任务队列。
- 如本轮不希望沉淀记忆，可传 `"memory_extraction": false`。

当前 mock 回复已经会读取：

- 占星模式下的 `sun_sign`
- 八字模式下的 `day_master` 和 `pillars`
- 混合模式下的 `sun_sign + day_master`

返回里会包含：

- `answer`
- `user_message`
- `assistant_message`
- `memory_updates`
- `context`
- `meta.mode`：`mock`、`simulated`、`live` 或 `fallback`

SSE 流式回复：

```http
GET /api/app/chat/sessions/{session_id}/stream?content=今天适合表达想法吗？
```

如果前端想把长期摘要异步化，可额外传：

```text
&memory_run_mode=queued
```

EventSource 示例：

```js
const url =
  `/api/app/chat/sessions/${sessionId}/stream` +
  `?content=${encodeURIComponent(message)}` +
  `&api_key=${encodeURIComponent(appApiKey)}`;
const events = new EventSource(url);
events.addEventListener("delta", (event) => {
  const { text } = JSON.parse(event.data);
  appendText(text);
});
events.addEventListener("done", (event) => {
  const { assistant_message_id } = JSON.parse(event.data);
  events.close();
});
```

当前 SSE 事件：

- `meta`：本次回复元信息。
- `delta`：分段文本。
- `memory`：本轮自动沉淀的记忆结果，新增 `summary_status` 和 `task_id`。
- `done`：完成事件，包含 `assistant_message_id`。

注意：当前 SSE 第一版会先完成后端回复编排，再按事件流吐给前端。后续会接 OpenAI 原生边生成边转发。

浏览器原生 `EventSource` 不能设置 `Authorization` header，所以 stream 接口额外支持 `api_key` 查询参数。生产环境如果使用 query token，建议换成短期 token；也可以用 `fetch` 读取 stream 并通过 header 传 App Key。

`reply` 和 `stream` 现在都会返回 `X-RateLimit-Limit`、`X-RateLimit-Remaining`、`X-RateLimit-Reset`。如果超过当前窗口，会返回 `429 app chat rate limit exceeded`，前端应该退避，不要立即重试。

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

## 自动记忆抽取

聊天回复会默认抽取轻量记忆候选：

- `preference`：用户表达的回答偏好，例如“先给结论”“更温和”“短回复”。
- `current_state`：用户近期状态，例如“最近在推进合作”。
- `relationship`：关系、伴侣、沟通、边界相关线索。
- `assistant_observation`：本轮回复里可辅助后续理解的轻量线索。

抽取结果会进入：

```http
GET /api/app/users/{user_id}/memories
```

第一版为规则抽取，不额外调用模型，避免增加成本。后续可升级为模型辅助抽取和去重。

## 后续待定接口

尚未实现：

- OpenAI 原生流式边生成边转发。
- 模型辅助记忆抽取、去重和遗忘策略。
- 完整星盘计算服务。
- 用户级额度、计费和权益。
