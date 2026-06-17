# Frontend API Contract

日期：2026-06-16

本文档给客户侧前端团队使用。后台管理、训练中心、模型配置等接口不在这里展开；前端客户产品主要接 `/api/app/*`。

## Base URL

本地开发：

```text
http://127.0.0.1:8812
```

生产环境以后替换为正式域名。

健康检查：

```http
GET /api/health
```

## Auth

所有 `/api/app/*` 接口需要 App Key。

普通 JSON API 推荐使用 header：

```http
Authorization: Bearer <app_api_key>
```

或：

```http
X-Nexa-API-Key: <app_api_key>
```

本地开发默认：

```text
dev-app-token
```

SSE 如果使用浏览器原生 `EventSource`，无法设置自定义 header。后端仅对 stream 接口额外支持：

```text
?api_key=<app_api_key>
```

生产建议前端优先使用 `fetch` 读取 stream 并带 header；如果必须用 `EventSource + api_key`，建议使用短期 token，避免长 token 出现在日志和浏览器历史里。

## Error Shape

FastAPI 默认错误：

```json
{
  "detail": "error message"
}
```

常见状态：

- `400`：请求字段不合法。
- `401`：App Key 无效。
- `429`：聊天频率超过当前限流窗口。
- `404`：用户、会话、模块等资源不存在。
- `500`：服务异常，前端展示通用失败提示即可。

## 1. 用户

### 创建或更新用户

```http
POST /api/app/users
```

说明：`external_id` 是幂等键。前端可传微信 openid、App 用户 ID 或自家账号 ID。

Request：

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

Response：

```json
{
  "id": 1,
  "external_id": "wechat-openid-123",
  "nickname": "max",
  "locale": "zh-CN",
  "timezone": "Asia/Shanghai",
  "status": "active",
  "profile": {
    "channel": "wechat"
  },
  "created_at": "2026-06-16T10:00:00",
  "updated_at": "2026-06-16T10:00:00"
}
```

### 查询用户

```http
GET /api/app/users/{user_id}
```

## 2. 本命资料和盘面

### 保存本命资料

```http
PUT /api/app/users/{user_id}/birth-profile
```

Request：

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

如果前端要保存八字基础资料，可在同一个接口里补充：

```json
{
  "chart_system": "bazi",
  "bazi_profile": {
    "year_pillar": "己巳",
    "month_pillar": "癸酉",
    "day_pillar": "乙丑",
    "hour_pillar": "甲申",
    "day_master": "乙木",
    "five_elements": {
      "wood": 2,
      "fire": 1,
      "earth": 2,
      "metal": 2,
      "water": 1
    },
    "ten_gods": ["比肩", "偏印"]
  }
}
```

说明：

- `chart_system` 当前支持 `astrology`、`bazi`、`hybrid`
- `bazi_profile` 这版是“输入型快照”，先保存上游算法或人工整理后的四柱事实
- 后续真实八字排盘服务接入后，仍复用同一个接口

Response 包含保存后的资料和 `chart_snapshot`。

### 获取盘面快照

```http
GET /api/app/users/{user_id}/chart
```

Response：

```json
{
  "user_id": 1,
  "birth_profile": {
    "birth_date": "1989-09-29",
    "birth_time": "16:00",
    "birth_city": "兰州",
    "chart_system": "astrology"
  },
  "chart_snapshot": {
    "system_type": "astrology",
    "calculation_level": "sun_sign_only",
    "sun_sign": "天秤座",
    "birth_datetime": "1989-09-29 16:00",
    "birth_city": "兰州",
    "birth_timezone": "Asia/Shanghai",
    "warnings": []
  },
  "warnings": []
}
```

八字模式示例：

```json
{
  "user_id": 1,
  "birth_profile": {
    "chart_system": "bazi",
    "bazi_profile": {
      "year_pillar": "己巳",
      "month_pillar": "癸酉",
      "day_pillar": "乙丑",
      "hour_pillar": "甲申",
      "day_master": "乙木"
    }
  },
  "chart_snapshot": {
    "system_type": "bazi",
    "calculation_level": "bazi_input_only",
    "pillars": {
      "year": "己巳",
      "month": "癸酉",
      "day": "乙丑",
      "hour": "甲申"
    },
    "day_master": "乙木"
  }
}
```

当前支持三种基础快照：

- `system_type=astrology`：`calculation_level=sun_sign_only`
- `system_type=bazi`：`calculation_level=bazi_input_only`
- `system_type=hybrid`：同时返回太阳星座和八字基础事实

完整上升、宫位、相位，以及八字大运、流年、藏干、旺衰，后续由专门计算服务补上。

### 触发一次盘面计算/回写

```http
POST /api/app/users/{user_id}/chart/calculate
```

用途：

- 前端保存完出生资料后，触发一次后端盘面计算
- 对接现有八字算法服务，把算法输出回写到用户资料
- 本地或联调阶段，可直接传模拟算法结果

联调示例：

```json
{
  "chart_system": "bazi",
  "simulate_algorithm_response": {
    "bazi_profile": {
      "year_pillar": "己巳",
      "month_pillar": "癸酉",
      "day_pillar": "乙丑",
      "hour_pillar": "甲申",
      "day_master": "乙木"
    }
  }
}
```

Response 重点字段：

```json
{
  "user_id": 1,
  "birth_profile": {},
  "chart_snapshot": {},
  "warnings": [],
  "meta": {
    "mode": "simulated",
    "provider": "bazi_calculator"
  }
}
```

说明：

- `mode=simulated`：使用了 `simulate_algorithm_response`
- `mode=live`：调用了真实八字算法服务
- `mode=snapshot`：没有触发远程算法，直接返回当前快照

## 3. 聊天会话

### 创建聊天会话

```http
POST /api/app/chat/sessions
```

Request：

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

Response：

```json
{
  "id": 10,
  "user_id": 1,
  "title": "今日咨询",
  "topic": "daily",
  "status": "active",
  "metadata": {
    "client": "web"
  },
  "messages": []
}
```

### 查询会话和消息

```http
GET /api/app/chat/sessions/{session_id}
```

### 追加消息

```http
POST /api/app/chat/sessions/{session_id}/messages
```

Request：

```json
{
  "role": "user",
  "content": "今天适合推进合作吗？",
  "metadata": {}
}
```

`role` 支持：

- `user`
- `assistant`
- `system`
- `tool`

## 4. 聊天回复

### 非流式回复

```http
POST /api/app/chat/sessions/{session_id}/reply
```

Request：

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

开发联调可以传：

```json
{
  "content": "今天适合推进合作吗？",
  "simulate_model_response": "可以推进，但先确认节奏、边界和对方反馈。"
}
```

行为：

- 自动保存本轮 `user` 消息。
- 组装用户资料、基础盘面、长期记忆、最近聊天、知识库命中。
- 生成回复。
- 自动保存 `assistant` 消息。
- 默认自动抽取长期记忆。
- `memory_run_mode` 可选：
  - `sync`：默认，同步更新 `memory_summary`
  - `queued`：立即落库 `memory_items`，把长期摘要更新交给 worker

Response 重点字段：

```json
{
  "session_id": 10,
  "status": "ok",
  "answer": "可以推进，但先确认节奏、边界和对方反馈。",
  "user_message": {},
  "assistant_message": {},
  "memory_updates": {
    "created_count": 2,
    "items": [],
    "summary": {},
    "summary_status": "updated",
    "task_id": null
  },
  "context": {
    "user": {},
    "birth_profile": {},
    "chart_snapshot": {},
    "memory": {},
    "recent_messages": [],
    "knowledge_hits": []
  },
  "meta": {
    "mode": "mock"
  }
}
```

`meta.mode` 可能是：

- `mock`
- `simulated`
- `live`
- `fallback`

成功响应头会带：

```http
X-RateLimit-Limit: 12
X-RateLimit-Remaining: 11
X-RateLimit-Reset: 1760300000
```

如果超过当前窗口限制，会返回：

```json
{
  "detail": "app chat rate limit exceeded"
}
```

关闭本轮记忆抽取：

```json
{
  "content": "这句话不要入记忆",
  "memory_extraction": false
}
```

如果希望把长期摘要异步化：

```json
{
  "content": "我喜欢先给结论，最近在推进合作。",
  "memory_run_mode": "queued"
}
```

此时返回里：

- `memory_updates.items`：本轮新增的记忆条目，已落库。
- `memory_updates.summary`：当前已存在的摘要快照，可能为 `null`。
- `memory_updates.summary_status`：`queued`
- `memory_updates.task_id`：本次摘要任务 ID

### SSE 流式回复

```http
GET /api/app/chat/sessions/{session_id}/stream?content=<urlencoded_message>
```

支持参数：

- `content`：必填，用户消息。
- `simulate_model_response`：可选，联调用。
- `memory_run_mode`：可选，`sync` 或 `queued`。
- `api_key`：可选，仅给原生 EventSource 使用。

#### 方式 A：fetch stream，推荐生产使用

```js
const response = await fetch(`/api/app/chat/sessions/${sessionId}/stream?content=${encodeURIComponent(message)}`, {
  headers: {
    Authorization: `Bearer ${appApiKey}`
  }
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = "";

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  // 按 SSE 格式解析 event/data。
}
```

#### 方式 B：EventSource，本地或短期 token 场景

```js
const url =
  `/api/app/chat/sessions/${sessionId}/stream` +
  `?content=${encodeURIComponent(message)}` +
  `&memory_run_mode=queued` +
  `&api_key=${encodeURIComponent(appApiKey)}`;

const events = new EventSource(url);

events.addEventListener("meta", (event) => {
  const meta = JSON.parse(event.data);
});

events.addEventListener("delta", (event) => {
  const { text } = JSON.parse(event.data);
  appendText(text);
});

events.addEventListener("memory", (event) => {
  const memoryUpdates = JSON.parse(event.data);
});

events.addEventListener("done", (event) => {
  const done = JSON.parse(event.data);
  events.close();
});
```

当前事件：

- `meta`
- `delta`
- `memory`：包含 `created_count`、`items`、`summary`、`summary_status`、`task_id`
- `done`

如果流式接口命中限流，会直接返回 `429`，并附带同样的 `X-RateLimit-*` 头。前端应做退避，不要立刻重建 `EventSource`。

## 5. 长期记忆

### 保存长期记忆摘要

```http
PUT /api/app/users/{user_id}/memory-summary
```

Request：

```json
{
  "summary": "用户偏好清晰直接的建议，关注合作和关系边界。"
}
```

### 新增记忆条目

```http
POST /api/app/users/{user_id}/memories
```

Request：

```json
{
  "memory_type": "preference",
  "content": "用户喜欢先给结论再解释。",
  "tags": ["偏好", "表达"],
  "importance": 4
}
```

### 查询用户记忆

```http
GET /api/app/users/{user_id}/memories
```

Response：

```json
{
  "user_id": 1,
  "summary": {
    "summary": "用户偏好清晰直接的建议。"
  },
  "items": [
    {
      "memory_type": "preference",
      "content": "用户喜欢先给结论再解释。",
      "tags": ["偏好", "表达"],
      "importance": 4
    }
  ]
}
```

## 6. App 页面/模块渲染

给前端直接取页面级 AI JSON：

```http
POST /api/app/pages/{page_slug}/render
```

给前端只取单模块 AI JSON：

```http
POST /api/app/modules/{module_slug}/render
```

常用页面：

- `birth-chart-reading`
- `daily-horoscope`
- `bazi-birth-reading`
- `bazi-daily-reading`

具体 module slug 可由后台模块中心或 `/api/modules` 查看。

渲染接口会自动合并用户上下文：

- 请求里传 `user_id` 后，后端会读取该用户保存的 `birth_profile`、`chart_snapshot` 和基础 `user_profile`
- 占星快照会注入到 `input_payload.astrology_facts`，并补充 `sun_sign`
- 八字快照会注入到 `input_payload.bazi_facts`、`bazi_profile`、`pillars`、`day_master`、`year_pillar`、`month_pillar`、`day_pillar`、`hour_pillar`
- 前端显式传入的同名字段优先生效；后端只补缺失字段

因此前端常规调用只需要传用户 ID、日期和业务主题：

```json
{
  "user_id": 1,
  "date": "2026-06-17",
  "input_payload": {
    "topic": "本命总览"
  }
}
```

## Recommended Flow

首次进入：

1. `POST /api/app/users`
2. `PUT /api/app/users/{user_id}/birth-profile`
3. 如果是八字或混合体系，`POST /api/app/users/{user_id}/chart/calculate`
4. `GET /api/app/users/{user_id}/chart`
5. `POST /api/app/chat/sessions`
6. `GET /api/app/chat/sessions/{session_id}/stream`

再次进入：

1. `POST /api/app/users`，使用同一个 `external_id` 幂等获取用户。
2. `GET /api/app/users/{user_id}/memories`
3. `POST /api/app/chat/sessions`
4. `POST /api/app/chat/sessions/{session_id}/reply` 或 SSE stream。

## Current Limitations

- 当前盘面快照只计算太阳星座。
- 当前 SSE 是后端先完成回复编排，再按事件流吐出；后续会接 OpenAI 原生 delta。
- 当前自动记忆抽取是规则版，不额外调用模型。
- 支付、套餐、额度尚未接入。
