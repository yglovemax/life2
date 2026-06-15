# 安全审计、后台登录与 App Key 管理

本项目第一版安全边界覆盖后台管理员登录、外部 App API、托管 App Key 和审计事件。高风险管理动作必须通过后台管理员会话访问。

## 后台登录

本地开发默认管理员账号：

```text
admin / admin123
```

生产环境部署前必须通过环境变量覆盖默认管理员用户名和密码：

- `NEXA_ADMIN_USERNAME`
- `NEXA_ADMIN_PASSWORD`

后台登录成功后会生成 `adm_` 前缀的会话 token。浏览器控制台只在本地存储当前会话 token，登出后服务端会撤销该会话。

当前已保护的后台接口：

- `GET /api/security/app-keys`
- `POST /api/security/app-keys`
- `POST /api/security/app-keys/{key_id}/revoke`
- `GET /api/security/audit-events`
- `GET /api/model-provider-keys`
- `POST /api/model-provider-keys`
- `POST /api/model-provider-keys/{key_id}/revoke`
- `POST /api/output-policies`
- `PUT /api/output-policies/{policy_id}`

## App Key

后台「安全审计」页面可以创建托管 App Key。

创建后平台只返回一次明文 token，数据库只保存：

- token 哈希
- token 前缀
- key 名称
- 权限范围
- 状态
- 创建时间、最近使用时间、撤销时间

不要把明文 token 写进代码库。移动端、Web 或服务端应通过自己的安全配置系统保存。

## 模型供应商 Key

后台「模型路由」页面可以保存模型供应商 Key。

创建后平台只返回一次明文 API Key，数据库只保存：

- key 哈希
- key 前缀
- 供应商
- key 名称
- 状态
- 创建时间、最近使用时间、撤销时间

当前后台保存的模型 Key 只用于配置、脱敏展示、路由预览和审计占位，数据库不会保存可逆明文。

真实模型调用使用运行时环境变量：

```bash
NEXA_MODEL_CALL_MODE=live
NEXA_OPENAI_API_KEY=<openai_api_key>
NEXA_OPENAI_BASE_URL=https://api.openai.com/v1
NEXA_MODEL_REQUEST_TIMEOUT_SECONDS=45
```

如果 `NEXA_MODEL_CALL_MODE=live` 但没有配置 `NEXA_OPENAI_API_KEY`，调用会进入 Fallback，并记录 `provider_key_missing`。如果模型返回不是合法 JSON，会记录 `invalid_json`；如果缺少 AI 生成的必填字段，会记录 `missing_required_fields`。

## 默认开发 Token

本地默认 token 是：

```text
dev-app-token
```

生产环境应通过 `NEXA_APP_API_TOKEN` 设置独立默认 token，或完全使用后台托管 App Key。

安全状态面板会提示是否仍在使用默认开发 token。

## 鉴权方式

App API 支持两种 Header：

```http
Authorization: Bearer <token>
```

或：

```http
X-Nexa-Api-Key: <token>
```

## 撤销

后台可以撤销某个 App Key。

撤销后：

- key 状态变为 `revoked`
- 记录撤销审计事件
- 使用该 token 调用 App API 会返回 `401`
- 鉴权失败也会写入审计事件

## 审计事件

当前记录：

- `admin_login_success`
- `admin_login_failed`
- `app_key_created`
- `app_key_revoked`
- `app_auth_failed`
- `app_module_render`
- `app_page_render`
- `model_provider_key_created`
- `model_provider_key_revoked`

审计事件不会保存完整 token，只保存必要的上下文，例如接口路径、request id、trace id、模块或页面标识。

## API

```http
POST /api/auth/login
GET /api/auth/me
POST /api/auth/logout
GET /api/security/status
GET /api/security/app-keys
POST /api/security/app-keys
POST /api/security/app-keys/{key_id}/revoke
GET /api/security/audit-events
GET /api/model-provider-keys
POST /api/model-provider-keys
POST /api/model-provider-keys/{key_id}/revoke
GET /api/output-policies
POST /api/output-policies
PUT /api/output-policies/{policy_id}
POST /api/model-router/preview
```

创建 key 示例：

```bash
ADMIN_SESSION="$(curl -s -X POST http://127.0.0.1:8812/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | python -c 'import json,sys; print(json.load(sys.stdin)["token"])')"

curl -X POST http://127.0.0.1:8812/api/security/app-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADMIN_SESSION" \
  -d '{
    "name": "iOS App Production",
    "scopes": ["app:render"],
    "operator": "admin"
  }'
```

返回里的 `token` 只出现一次。
