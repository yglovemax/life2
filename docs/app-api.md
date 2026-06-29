# App API 对接说明

Nexa App 使用 `/api/app/*` 接口获取正式 JSON 输出。后台测试接口仍然保留在 `/api/modules/*/test-run`，两类调用通过 `CallTrace.request_type` 隔离。

## 鉴权

所有 App 接口都需要 Token。

本地默认：

```text
dev-app-token
```

生产环境应通过 `NEXA_APP_API_TOKEN` 环境变量覆盖默认值，值使用生产专用 token。

支持两种 Header：

```http
Authorization: Bearer dev-app-token
```

或：

```http
X-Nexa-Api-Key: dev-app-token
```

聊天 `reply` 和 `stream` 接口还会返回：

```http
X-RateLimit-Limit: 12
X-RateLimit-Remaining: 11
X-RateLimit-Reset: 1760300000
```

如果同一 App Key 在同一聊天会话窗口内超过限制，接口会返回 `429` 和 `app chat rate limit exceeded`。

## 页面级 JSON API

```http
POST /api/app/pages/{page_slug}/render
```

当前一期页面：

- `birth-chart-reading`
- `daily-horoscope`
- `bazi-birth-reading`
- `bazi-daily-reading`

只会渲染状态为 `gray` 或 `live` 的模块，草稿、待测、停用和已回滚模块不会出现在 App 输出里。

示例：

```bash
curl -X POST http://127.0.0.1:8812/api/app/pages/birth-chart-reading/render \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-app-token" \
  -d '{
    "user_id": 1,
    "date": "2026-06-15",
    "input_payload": {
      "nickname": "max",
      "sun_sign": "白羊座",
      "moon_sign": "处女座"
    }
  }'
```

返回结构：

```json
{
  "request_id": "req_xxx",
  "page": {
    "id": 1,
    "slug": "birth-chart-reading",
    "name": "出生星盘解读页"
  },
  "modules": [],
  "meta": {
    "request_type": "official",
    "module_count": 0
  }
}
```

说明：如果请求带数字 `user_id`，渲染前后端会自动读取该用户保存的本命资料和盘面快照，并把占星/八字事实补进 `input_payload`。八字页会自动获得 `bazi_facts`、`bazi_profile`、`pillars`、`day_master` 和四柱字段，前端不用每次重复拼四柱。带 `date` 渲染八字/混合页面时，还会补 `daily_transit` 基础日运上下文；真实流日算法接入后，可由前端或上游服务显式传入同名字段覆盖。

## 模块级 JSON API

```http
POST /api/app/modules/{module_slug}/render
```

示例：

```bash
curl -X POST http://127.0.0.1:8812/api/app/modules/birth-basic-chart-info/render \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-app-token" \
  -d '{
    "user_id": 1,
    "date": "2026-06-15",
    "input_payload": {
      "nickname": "max",
      "sun_sign": "白羊座"
    }
  }'
```

返回结构：

```json
{
  "request_id": "req_xxx",
  "trace_id": 1,
  "module": {
    "id": 1,
    "slug": "birth-basic-chart-info",
    "name": "用户基础星盘信息",
    "version": 2,
    "status": "live"
  },
  "result": {},
  "meta": {
    "request_type": "official",
    "model_name": "GPT-5.4 Mini",
    "prompt_version": 1,
    "estimated_cost_cents": 1
  }
}
```

## 追踪与隔离

- App 正式调用：`request_type=official`
- 后台测试调用：`request_type=test`
- 每次 App 调用都会返回 `request_id`
- 每个模块输出都会写入 `call_traces` 并返回 `trace_id`
- 后台可通过 `GET /api/call-traces?request_type=official` 查看正式调用

## 状态规则

App API 只允许读取已发布模块：

- `gray`
- `live`

不对 App 输出的状态：

- `draft`
- `pending_test`
- `test_passed`
- `pending_approval`
- `rolled_back`
- `disabled`

## 本命资料扩展

`PUT /api/app/users/{user_id}/birth-profile` 现在除了占星基础资料，也支持保存八字基础事实：

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

当前约定：

- `chart_system` 支持 `astrology`、`bazi`、`hybrid`
- 占星返回 `system_type=astrology`
- 八字返回 `system_type=bazi`
- 混合资料返回 `system_type=hybrid`

这版八字属于“输入型快照”，用于先接前端和算法结果，不代表完整八字排盘引擎已经上线。

如果需要把上游八字算法结果写回当前用户，可调用：

```http
POST /api/app/users/{user_id}/chart/calculate
```

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

返回会包含：

- 最新 `birth_profile`
- 最新 `chart_snapshot`
- `meta.mode`：`simulated`、`live` 或 `snapshot`

生产接真实八字算法服务时，可配置：

- `NEXA_BAZI_CALC_MODE=live`
- `NEXA_BAZI_API_URL`
- `NEXA_BAZI_API_TOKEN`

## 通用占卜 Agent API

Agent API 是客户侧新的统一入口，复用现有聊天会话和记忆系统，并额外返回占术路由、确认按钮、工具调用协议和推荐结构。

### 创建 Agent 会话

```http
POST /api/app/agent/sessions
```

```json
{
  "user_id": 1,
  "entry_type": "preset_question",
  "entry_context": {
    "page_slug": "daily-horoscope",
    "module_slug": "daily-key-transits",
    "system": "astrology",
    "preset_question": "这对我有什么影响？"
  },
  "title": "这对我有什么影响？"
}
```

返回值是 `topic=agent` 的聊天会话，入口上下文保存在 `metadata.agent`。

### 路由预览

```http
POST /api/app/agent/route-preview
```

```json
{
  "content": "我该不该答应朋友这个具体事情？",
  "entry_type": "free_question",
  "entry_context": {
    "system": "astrology"
  }
}
```

如果自动推荐占术和当前入口不一致，会返回：

```json
{
  "route_source": "auto_match",
  "selected_system": "astrology",
  "recommended_system": "liuyao",
  "needs_confirmation": true,
  "quick_actions": [
    {
      "label": "用六爻看",
      "value": "liuyao"
    }
  ]
}
```

### 工具注册表

```http
GET /api/app/agent/tools
```

返回所有 Agent 工具的只读注册信息：

```json
{
  "items": [
    {
      "tool_name": "astrology_birth_chart",
      "system": "astrology",
      "requires_birth_profile": true,
      "requires_relation_profile": false,
      "requires_paid_access": false,
      "provider_status": "connected_context"
    },
    {
      "tool_name": "tarot_reading",
      "system": "tarot",
      "requires_birth_profile": false,
      "requires_relation_profile": false,
      "requires_paid_access": false,
      "provider_status": "provider_placeholder"
    }
  ]
}
```

### Agent 回复

```http
POST /api/app/agent/sessions/{session_id}/reply
```

```json
{
  "content": "他现在怎么想我？",
  "memory_enabled": true
}
```

重点返回：

```json
{
  "status": "ok",
  "answer": "更适合先用塔罗看当下状态。",
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
        "entry_type": "free_question"
      },
      "output_payload": {
        "protocol_status": "awaiting_provider"
      },
      "data_source": "v1_tool_protocol",
      "status": "ok",
      "error": ""
    }
  ],
  "messages": {
    "user_message_id": 1,
    "assistant_message_id": 2
  }
}
```

Phase A 已实现：

- 用户明确占术优先。
- 页面预设问题绑定当前页面体系。
- 自由提问自动路由。
- 推荐占术和当前入口不一致时返回 `quick_actions` 等待确认。
- `tool_calls` 输出标准结构。

Phase B 已实现：

- `GET /api/app/agent/tools` 工具注册表。
- 占星、八字、hybrid 工具读取现有 `chart_snapshot`。
- 塔罗、六爻、合盘、签文返回稳定 provider 占位协议，不编造真实抽牌、卦象或签文。
- 合盘缺少关系对象资料时返回 `status=needs_input`、`error=relation_profile_required`。

### Agent SSE

```http
GET /api/app/agent/sessions/{session_id}/stream?content=<urlencoded_message>
```

事件顺序固定为：

```text
route
tool_call
delta
recommendations
memory
done
```

`EventSource` 场景可用 query token：

```text
GET /api/app/agent/sessions/10/stream?api_key=dev-app-token&content=...
```

用户点击确认按钮后，可传：

```text
confirmed_system=liuyao
```

Phase C 已实现：

- Agent 专用 SSE。
- 支持 header 鉴权和 `api_key` query 鉴权。
- SSE 支持 `confirmed_system` 快捷确认参数。

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

Response 会回填 `user_id`、`session_id`、`message_id`，用于后续统计每个模型、占术路由和推荐位的效果。

### Agent 记忆控制

```http
GET /api/app/users/{user_id}/memory-settings
PUT /api/app/users/{user_id}/memory-settings
DELETE /api/app/users/{user_id}/memories/{memory_id}
```

`PUT /memory-settings` Request：

```json
{
  "memory_enabled": false,
  "personalization_enabled": false,
  "retention_days": 30
}
```

- `memory_enabled=false`：Agent 回复时不再沉淀新记忆。
- `personalization_enabled=false`：Agent 回复时不把长期记忆放入本轮上下文，`memory_used=[]`。
- 删除记忆为软删除，列表接口只返回 `active` 条目。

Phase D 已实现：

- Agent message feedback API。
- 用户记忆条目删除。
- 用户记忆设置读写。
- Agent 回复尊重 `memory_enabled` 与 `personalization_enabled`。

Phase D 后续继续补：

- 真实塔罗、六爻、合盘、签文工具 provider。
- 更细粒度的向量相关性筛选。
