# Nexa AI API Admin

Nexa 占卜 APP 的 AI API 管理后台。

本项目按 `docs/requirements/Nexa占卜APP_AI_API管理后台_开发需求文档.md` 原版需求逐步实现。第一期目标是让团队可以围绕星座/占星页面完成模块管理、Prompt 调试、字段契约、模型选择、测试追踪、Fallback 和发布协作。

## 当前阶段

Phase 1 已完成第一版闭环：

- 模块中心和模块详情
- Prompt 五段式配置
- 字段契约配置
- 模型配置
- 模型供应商 Key 管理、模型路由和输出策略
- 真实模型调用适配层（默认 mock，可通过环境变量开启 OpenAI Responses API）
- 模型原始返回 JSON 校验、缺字段自动 Fallback
- 测试中心和人工评分
- 问题追踪和责任流转
- 知识库录入与轻量检索
- 成本中心和 Fallback 告警
- 发布中心、灰度、上线、回滚
- App 页面级 / 模块级 JSON API
- 正式调用与测试调用隔离
- App Key 管理和安全审计
- 后台登录、管理员会话和敏感接口保护

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8812
```

打开：

- 后台页面：http://127.0.0.1:8812/admin
- API 文档：http://127.0.0.1:8812/docs

本地默认后台账号为 `admin / admin123`。生产部署前请覆盖 `NEXA_ADMIN_USERNAME` 和 `NEXA_ADMIN_PASSWORD`。

模型调用默认不出网，方便本地开发和测试：

```bash
NEXA_MODEL_CALL_MODE=mock
```

生产需要真实调用 OpenAI 时设置：

```bash
export NEXA_MODEL_CALL_MODE=live
export NEXA_OPENAI_API_KEY="<openai_api_key>"
```

后台保存的模型供应商 Key 只做配置、脱敏展示和审计占位；实际运行时 Key 读取 `NEXA_OPENAI_API_KEY`，避免数据库保存可逆明文密钥。

App 对接说明见：`docs/app-api.md`
安全审计说明见：`docs/security.md`

## 测试

```bash
pytest
```

## 项目边界

这是独立项目，只服务 Nexa AI API 管理后台，不与 `life`、`astro_daily_agent` 或其他旧项目混写。
