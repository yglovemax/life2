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

## 3. 通用占卜 Agent

Agent 是客户侧推荐主入口。它底层复用聊天会话，但会额外返回占术路由、确认按钮、工具调用协议和推荐结构。

### 创建 Agent 会话

```http
POST /api/app/agent/sessions
```

自由提问入口：

```json
{
  "user_id": 1,
  "entry_type": "free_question",
  "entry_context": {
    "system": "astrology"
  },
  "title": "个人占卜 Agent"
}
```

页面预设问题入口：

```json
{
  "user_id": 1,
  "entry_type": "preset_question",
  "entry_context": {
    "page_slug": "daily-horoscope",
    "module_slug": "daily-key-transits",
    "system": "astrology",
    "preset_question": "这对我有什么影响？",
    "current_page_data": {}
  },
  "title": "这对我有什么影响？"
}
```

Response 仍是聊天会话结构，但 `topic=agent`，并在 `metadata.agent` 中保存入口上下文：

```json
{
  "id": 10,
  "user_id": 1,
  "title": "个人占卜 Agent",
  "topic": "agent",
  "metadata": {
    "agent": {
      "entry_type": "free_question",
      "entry_context": {
        "system": "astrology"
      },
      "active_system": "astrology",
      "last_route": {}
    }
  },
  "messages": []
}
```

### 路由预览

```http
POST /api/app/agent/route-preview
```

用途：前端输入时预判占术，或者后台/联调验证路由规则。

```json
{
  "content": "我该不该答应朋友这个具体事情？",
  "entry_type": "free_question",
  "entry_context": {
    "system": "astrology"
  }
}
```

Response：

```json
{
  "entry_type": "free_question",
  "route_source": "auto_match",
  "selected_system": "astrology",
  "recommended_system": "liuyao",
  "needs_confirmation": true,
  "reason": "这是具体事件决策问题，更适合用六爻看局势、风险和短期结果。当前入口是占星，所以先不自动切换，等待用户确认。",
  "quick_actions": [
    {
      "label": "用六爻看",
      "value": "liuyao",
      "action": {
        "type": "confirm_route",
        "payload": {
          "selected_system": "liuyao"
        }
      }
    }
  ]
}
```

前端规则：

- `needs_confirmation=true` 时必须展示 `quick_actions`。
- 用户点击快捷按钮后，下一次 reply 带 `confirmed_route.selected_system`。
- 页面预设问题首轮不会自动切换占术。
- 用户明确输入“只用八字/用塔罗/起六爻”等，会直接覆盖自动路由。

### 工具注册表

```http
GET /api/app/agent/tools
```

Response：

```json
{
  "items": [
    {
      "tool_name": "bazi_birth_chart",
      "system": "bazi",
      "requires_birth_profile": true,
      "requires_relation_profile": false,
      "requires_paid_access": false,
      "provider_status": "connected_context",
      "output_contract": {
        "status": ["ok", "needs_input", "error"],
        "required_fields": [
          "tool_name",
          "system",
          "input_payload",
          "output_payload",
          "status",
          "error",
          "data_source"
        ]
      }
    }
  ]
}
```

`provider_status`：

- `connected_context`：当前已接现有 Nexa 结构化上下文，比如占星、八字、hybrid。
- `local_provider`：已接本地结构化 provider，比如塔罗、六爻、签文、合盘。
- `provider_placeholder`：工具协议已稳定，但真实 provider 尚未接入的预留状态。

### Agent 回复

```http
POST /api/app/agent/sessions/{session_id}/reply
```

Request：

```json
{
  "content": "他现在怎么想我？",
  "memory_enabled": true
}
```

用户点击确认按钮后的 Request：

```json
{
  "content": "那就用六爻看",
  "confirmed_route": {
    "selected_system": "liuyao"
  }
}
```

Response：

```json
{
  "session_id": 10,
  "status": "ok",
  "answer": "max，我先按这组三张牌看“他现在怎么想我？”。现状是「女祭司」...",
  "route": {
    "route_source": "auto_match",
    "selected_system": "tarot",
    "recommended_system": "tarot",
    "needs_confirmation": false
  },
  "tool_calls": [
    {
      "tool_name": "tarot_reading",
      "system": "tarot",
      "input_payload": {
        "content": "他现在怎么想我？",
        "entry_type": "free_question",
        "route_source": "auto_match"
      },
      "output_payload": {
        "protocol_status": "computed",
        "provider": "local_tarot_provider_v1",
        "spread_type": "three_card",
        "cards": [
          {
            "position": "现状",
            "name": "女祭司",
            "orientation": "upright",
            "keywords": ["直觉", "观察", "隐情"],
            "message": "答案不适合催出来，先观察对方真实行动。"
          }
        ]
      },
      "data_source": "local_tarot_provider_v1",
      "needs_birth_info": false,
      "needs_relation_profile": false,
      "needs_paid_access": false,
      "status": "ok",
      "error": ""
    }
  ],
  "memory_used": [],
  "recommendations": [],
  "messages": {
    "user_message_id": 1,
    "assistant_message_id": 2
  },
  "memory_updates": {},
  "context": {},
  "meta": {
    "mode": "mock"
  }
}
```

`selected_system` 当前支持：

- `astrology`
- `bazi`
- `tarot`
- `liuyao`
- `synastry`
- `oracle`
- `hybrid_transit`

`tool_calls.status`：

- `ok`：工具调用协议已完成；`output_payload.protocol_status=computed` 表示本轮已生成结构化工具结果。
- `provided`：如果 `output_payload.protocol_status=provided`，表示使用了前端或上游传入的工具结果。
- `needs_input`：需要用户补资料，例如合盘缺少对方资料时返回 `error=relation_profile_required`。
- `error`：工具名未知或 provider 异常。

占星、八字、hybrid 工具会从现有用户 `chart_snapshot` 读取结构化结果，并放入 `output_payload.chart_snapshot`。

本地 provider 输出位置：

- 塔罗：`output_payload.cards`，固定三张牌：现状、阻力、建议。
- 六爻：`output_payload.hexagram`，包含 `upper_trigram`、`lower_trigram`、`lines`、`moving_lines`。
- 签文：`output_payload.draw`，包含 `title`、`keyword`、`message`、`action`。
- 合盘：`output_payload.compatibility`，包含 `score`、`level`、`dimensions`。

回答编排规则：

- 后端会先生成 `tool_calls`，再生成 `answer`。
- `answer` 会优先基于 `tool_calls.output_payload` 组织话术。
- 前端展示时可以直接显示 `answer`，也可以把 `tool_calls` 单独渲染成卡牌、卦象、签文或合盘组件。
- 如果 `tool_calls.status=needs_input`，`answer` 会引导用户补资料。

### Agent SSE 流式回复

```http
GET /api/app/agent/sessions/{session_id}/stream?content=<urlencoded_message>
```

支持 query 参数：

- `content`：必填，用户消息。
- `simulate_model_response`：可选，联调用。
- `memory_run_mode`：可选，`sync` 或 `queued`。
- `selected_system`：可选，用户显式选择占术。
- `confirmed_system`：可选，用户点击确认按钮后的占术，例如 `liuyao`。
- `memory_enabled`：可选，`false` 时本轮不抽取记忆。
- `api_key`：可选，仅给原生 `EventSource` 使用。

事件顺序：

```text
route
tool_call
delta
recommendations
memory
done
```

示例：

```js
const url =
  `/api/app/agent/sessions/${sessionId}/stream` +
  `?content=${encodeURIComponent(message)}` +
  `&api_key=${encodeURIComponent(appApiKey)}`;

const events = new EventSource(url);

events.addEventListener("route", (event) => {
  const route = JSON.parse(event.data);
  renderRoute(route);
});

events.addEventListener("tool_call", (event) => {
  const toolCall = JSON.parse(event.data);
  renderToolCall(toolCall);
});

events.addEventListener("delta", (event) => {
  const { text } = JSON.parse(event.data);
  appendAgentText(text);
});

events.addEventListener("recommendations", (event) => {
  const { items } = JSON.parse(event.data);
  renderRecommendations(items);
});

events.addEventListener("memory", (event) => {
  const memoryUpdates = JSON.parse(event.data);
  updateMemoryState(memoryUpdates);
});

events.addEventListener("done", (event) => {
  const done = JSON.parse(event.data);
  finalizeAgentMessage(done.messages);
  events.close();
});
```

用户点击确认按钮后，前端可以这样传：

```text
confirmed_system=liuyao
```

后端会等价转换为：

```json
{
  "confirmed_route": {
    "selected_system": "liuyao"
  }
}
```

### Agent 反馈

```http
POST /api/app/agent/messages/{message_id}/feedback
```

Request：

```json
{
  "feedback_type": "like",
  "target_type": "recommendation",
  "target_id": "tarot_reading",
  "metadata": {
    "clicked_recommendation": "tarot_reading"
  }
}
```

Response：

```json
{
  "id": 1,
  "user_id": 10,
  "session_id": 20,
  "message_id": 30,
  "feedback_type": "like",
  "target_type": "recommendation",
  "target_id": "tarot_reading",
  "metadata": {
    "clicked_recommendation": "tarot_reading"
  },
  "created_at": "2026-06-29T00:00:00+00:00"
}
```

推荐用法：

- 用户点赞/点踩回答：`target_type=message`。
- 用户点击推荐占术/付费报告：`target_type=recommendation`，`target_id` 放推荐项 ID。
- 用户投诉或标记不准：`feedback_type=dislike` 或 `report`，原因放 `metadata.reason`。

## 4. 聊天会话

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

## 5. 聊天回复

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

## 6. 长期记忆

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
      "importance": 4,
      "embedding": {
        "status": "ready",
        "model": "text-embedding-3-small",
        "hash": "...",
        "dimensions": 1536,
        "provider": "mock"
      }
    }
  ]
}
```

### 删除记忆条目

```http
DELETE /api/app/users/{user_id}/memories/{memory_id}
```

说明：后端执行软删除，删除后的条目不会再出现在 `GET /memories` 结果里。

### 记忆设置

```http
GET /api/app/users/{user_id}/memory-settings
PUT /api/app/users/{user_id}/memory-settings
```

`PUT` Request：

```json
{
  "memory_enabled": false,
  "personalization_enabled": false,
  "retention_days": 30
}
```

Response：

```json
{
  "user_id": 1,
  "memory_enabled": false,
  "personalization_enabled": false,
  "retention_days": 30,
  "updated_at": "2026-06-29T00:00:00+00:00"
}
```

- `memory_enabled=false`：不再沉淀新记忆。
- `personalization_enabled=false`：本轮 Agent 不使用长期记忆做个性化。

`embedding` 是后端检索元数据；SQLite 本地可能是 mock，PostgreSQL 生产环境可同步写入 pgvector 列。前端展示时可以忽略。

## 7. App 页面/模块渲染

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
- 带 `date` 的八字/混合渲染会补 `input_payload.daily_transit`，当前是稳定占位，后续可替换为真实流日/流月算法结果
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

`daily_transit` 当前结构：

```json
{
  "system_type": "bazi_daily",
  "date": "2026-06-17",
  "base_day_master": "乙木",
  "base_pillars": {
    "year": "己巳",
    "month": "癸酉",
    "day": "乙丑",
    "hour": "甲申"
  },
  "calculation_level": "daily_transit_placeholder",
  "source": "local_placeholder",
  "warnings": ["当前版本尚未接入真实流日/流月计算服务，daily_transit 仅用于稳定接口和提示词上下文。"]
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
