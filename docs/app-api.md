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

只会渲染状态为 `gray` 或 `live` 的模块，草稿、待测、停用和已回滚模块不会出现在 App 输出里。

示例：

```bash
curl -X POST http://127.0.0.1:8812/api/app/pages/birth-chart-reading/render \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-app-token" \
  -d '{
    "user_id": "app_user_001",
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
    "user_id": "app_user_001",
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
