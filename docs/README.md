# Nexa Docs Index

日期：2026-06-18

这个目录是 `yglovemax/life2` 的项目说明中心。后续开发、前端联调、部署、排查问题，都先从这里找入口，避免功能散在聊天记录里。

## 建议阅读顺序

1. `project-memory.md`
   - 当前产品目标、已经做完的能力、关键技术决策、明确边界。
   - 新人接手或继续开发前先读这一份。
2. `codebase-guide.md`
   - 代码目录、核心文件职责、模型分组、路由分组、测试覆盖。
   - 改代码前先对照这一份，避免把功能写错位置。
3. `feature-catalog.md`
   - 已有功能按模块整理，包含状态、入口接口、说明文档。
   - 产品验收和排期时用这一份。
4. `architecture.md`
   - 整体架构和调用链路。
5. `backend-integration.md`
   - 后台、训练、知识库、embedding、worker 等后端接口说明。
6. `frontend-api-contract.md`
   - 客户端前端团队对接 `/api/app/*` 时使用。
7. `app-api.md`
   - App 正式 JSON 输出、用户资料、盘面、聊天和长期记忆接口说明。
8. `phase2-production-foundation.md`
   - 生产化底座：Postgres、pgvector、Redis、worker、embedding 重建。
9. `security.md`
   - 后台登录、App Key、模型供应商 Key、安全审计。
10. `reuse-inventory.md`
   - 旧项目可复用能力梳理。

## 原始需求

- `requirements/Nexa占卜APP_AI_API管理后台_开发需求文档.md`

原始需求保持归档，不直接覆盖。新增功能和实现说明写入上面的项目文档。

## 维护规则

- 新增后端接口：同步更新 `backend-integration.md`，如果是 App 给前端用，还要更新 `frontend-api-contract.md` 或 `app-api.md`。
- 新增核心功能：同步更新 `feature-catalog.md`。
- 新增架构决策或边界：同步更新 `project-memory.md`。
- 新增重要代码目录或测试文件：同步更新 `codebase-guide.md`。
- 不要把 API Key、服务器密码、用户隐私资料写入文档或提交到仓库。
