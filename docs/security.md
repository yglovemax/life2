# 安全审计与 App Key 管理

本项目第一版安全边界先覆盖外部 App API。后台管理接口暂时保持本地可用，后续生产部署前再加入后台登录、角色和操作审批。

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

- `app_key_created`
- `app_key_revoked`
- `app_auth_failed`
- `app_module_render`
- `app_page_render`

审计事件不会保存完整 token，只保存必要的上下文，例如接口路径、request id、trace id、模块或页面标识。

## API

```http
GET /api/security/status
GET /api/security/app-keys
POST /api/security/app-keys
POST /api/security/app-keys/{key_id}/revoke
GET /api/security/audit-events
```

创建 key 示例：

```bash
curl -X POST http://127.0.0.1:8812/api/security/app-keys \
  -H "Content-Type: application/json" \
  -d '{
    "name": "iOS App Production",
    "scopes": ["app:render"],
    "operator": "admin"
  }'
```

返回里的 `token` 只出现一次。
