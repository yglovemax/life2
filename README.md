# Nexa AI API Admin

Nexa 占卜 APP 的 AI API 管理后台。

本项目按 `docs/requirements/Nexa占卜APP_AI_API管理后台_开发需求文档.md` 原版需求逐步实现。第一期目标是让团队可以围绕星座/占星页面完成模块管理、Prompt 调试、字段契约、模型选择、测试追踪、Fallback 和发布协作。

## 当前阶段

第一批代码先交付可运行骨架：

- 模块中心
- 模块详情
- Prompt 五段式数据结构
- 字段契约数据结构
- 模型配置
- 单模块测试接口
- 调用追踪记录
- 两个一期页面的预置模块

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

## 测试

```bash
pytest
```

## 项目边界

这是独立项目，只服务 Nexa AI API 管理后台，不与 `life`、`astro_daily_agent` 或其他旧项目混写。
