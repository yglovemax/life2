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

运行时状态：

```http
GET /api/runtime/status
```

用于查看当前数据库后端、脱敏数据库 URL、连接状态，以及 PostgreSQL/pgvector 规划和安装状态。SQLite 本地开发会返回 `pgvector.planned=false`；生产切到 PostgreSQL 后，执行 Alembic 迁移会为 `knowledge_chunks` 和 `memory_items` 准备 `vector(1536)` embedding 列与 ivfflat cosine 索引。

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

渲染请求带数字 `user_id` 时，后端会自动把该用户的资料并入模块调用上下文：

- `user_profile`：App 用户基础资料
- `birth_profile`：保存过的出生/本命资料
- `chart_snapshot`：当前盘面快照
- `astrology_facts` / `sun_sign`：占星基础事实
- `bazi_facts` / `bazi_profile` / `pillars` / `day_master` / 四柱字段：八字基础事实
- `daily_transit`：请求带 `date` 且盘面为八字/混合时自动补充的日运上下文

`daily_transit` 当前是 `daily_transit_placeholder`，用于让八字日运页先稳定对接。真实流日/流月算法接入后，可以由上游在 `input_payload.daily_transit` 显式传入并覆盖。

前端团队不需要在每个模块调用里重复传四柱或基础日运上下文；如果确实要临时覆盖，可在 `input_payload` 里显式传同名字段。

## 知识库接口

Markdown / 手工知识：

```http
POST /api/knowledge-sources
POST /api/knowledge-entries
GET /api/knowledge-sources
GET /api/knowledge-chunks
GET /api/knowledge/duplicates
GET /api/knowledge/cleanup-recommendations
POST /api/knowledge/search
```

资料生命周期：

```http
POST /api/knowledge-sources/{source_id}/archive
POST /api/knowledge-sources/{source_id}/restore
DELETE /api/knowledge-sources/{source_id}
POST /api/knowledge-sources/{source_id}/merge
```

- `archive`：把资料状态改为 `archived`，历史记录和 chunks 保留，但不会再进入 `/api/knowledge/search` 检索结果。
- `restore`：把归档资料恢复为 `active`，恢复后重新参与检索。
- `DELETE`：硬删除未被训练运行引用的资料，并删除其 chunks。若资料已被 `TrainingRun.source_id` 或 `TrainingRun.published_source_id` 引用，接口返回 `400`，应改用归档，避免破坏训练版本记录。
- `merge`：把重复资料合并到目标资料，默认只允许内容指纹完全一致。被合并的资料会改为 `archived`，主资料保留并继续参与检索，动作写入 `knowledge_source_merged` 审计事件。

`POST /api/knowledge-sources` 会做轻量重复检测。返回里的 `duplicate` 字段用于后台提示是否已经存在同内容资料：

```json
{
  "id": 12,
  "title": "占星资料 2026-06",
  "status": "active",
  "chunk_count": 24,
  "duplicate": {
    "is_duplicate": true,
    "source_id": 8,
    "title": "占星资料旧版",
    "status": "active"
  }
}
```

重复组查询：

```http
GET /api/knowledge/duplicates
```

返回示例：

```json
{
  "items": [
    {
      "fingerprint": "f3d...",
      "source_count": 2,
      "active_count": 2,
      "canonical_source": {"id": 8, "title": "占星资料旧版"},
      "sources": [
        {"id": 8, "title": "占星资料旧版", "status": "active"},
        {"id": 12, "title": "占星资料重复上传", "status": "active"}
      ]
    }
  ]
}
```

合并重复源：

```json
{
  "target_source_id": 8,
  "operator": "qa"
}
```

如果两份内容不一致，默认返回 `400`，避免误合并。确有人工确认的特殊情况，可传 `force=true`。

清理建议：

```http
GET /api/knowledge/cleanup-recommendations
POST /api/knowledge/cleanup-recommendations/execute
```

该接口只生成建议，不会执行删除或合并。当前会返回两类建议：

- `merge_duplicate_source`：内容指纹完全一致，建议调用 merge 合并重复源。
- `delete_archived_unused_source`：资料已归档且没有训练运行引用，建议走 DELETE 硬删除。

返回示例：

```json
{
  "summary": {
    "total": 2,
    "by_action": {
      "merge_duplicate_source": 1,
      "delete_archived_unused_source": 1
    }
  },
  "items": [
    {
      "action": "merge_duplicate_source",
      "severity": "medium",
      "source_id": 12,
      "target_source_id": 8,
      "method": "POST",
      "endpoint": "/api/knowledge-sources/12/merge",
      "payload": {"target_source_id": 8},
      "safe_to_run": true
    }
  ]
}
```

执行选中的建议：

```json
{
  "recommendation_ids": [
    "merge_duplicate_source:12:8",
    "delete_archived_unused_source:15"
  ],
  "operator": "qa"
}
```

执行接口会先重新读取当前建议清单，只执行仍然有效的建议。过期或伪造的 `recommendation_id` 会返回 failed，不会盲目操作。返回示例：

```json
{
  "summary": {
    "requested": 2,
    "completed": 2,
    "failed": 0
  },
  "items": [
    {
      "recommendation_id": "merge_duplicate_source:12:8",
      "action": "merge_duplicate_source",
      "source_id": 12,
      "target_source_id": 8,
      "status": "completed",
      "error": ""
    }
  ]
}
```

每次批处理会写入 `knowledge_cleanup_executed` 审计事件；单条 merge 仍会写入 `knowledge_source_merged` 审计事件。

## 算法库接口

算法库和知识库分工不同：

- 知识库保存解释材料、表达规则、案例和咨询话术，用于检索增强。
- 算法库保存确定性计算规则，用于按用户输入输出结构化结果，再交给模块或聊天编排表达。

第一版只执行安全 JSON `rule_spec`，不执行上传的 Python、JavaScript、Shell 或任意代码。

接口：

```http
GET /api/algorithms
POST /api/algorithms
POST /api/algorithms/uploads
GET /api/algorithms/{algorithm_id}
POST /api/algorithms/{algorithm_id}/test-run
POST /api/algorithms/{algorithm_id}/publish
POST /api/algorithms/{algorithm_id}/execute
```

创建算法草稿：

```json
{
  "slug": "bazi-day-master-score",
  "name": "日主评分算法",
  "domain": "bazi",
  "algorithm_type": "rule_spec",
  "spec": {
    "output_template": {
      "day_master": "{{input.day_master}}",
      "score": "{{map.day_master_scores[input.day_master]}}",
      "label": "{{map.labels[input.day_master]}}"
    },
    "maps": {
      "day_master_scores": {"甲木": 82, "乙木": 76},
      "labels": {"甲木": "主动开局", "乙木": "柔韧生长"}
    }
  },
  "input_schema": {"required": ["day_master"]},
  "output_schema": {"required": ["day_master", "score", "label"]}
}
```

测试执行不要求发布：

```json
{
  "input_payload": {"day_master": "甲木"},
  "operator": "qa"
}
```

发布后才能正式执行：

```http
POST /api/algorithms/{algorithm_id}/publish
POST /api/algorithms/{algorithm_id}/execute
```

正式执行返回 `AlgorithmRun`，包含 `input_payload`、`output_payload`、`run_mode`、`status` 和版本 ID。前端或上游服务可先调用算法得到结构化结果，再把结果传入 `/api/app/modules/{module_slug}/render` 的 `input_payload`。

知识片段创建后会自动生成本地 mock embedding 元数据，返回的 chunk 会包含：

```json
{
  "embedding": {
    "status": "ready",
    "model": "text-embedding-3-small",
    "hash": "...",
    "dimensions": 1536,
    "provider": "mock"
  },
  "semantic_score": 0
}
```

`POST /api/knowledge/search` 当前会返回 `semantic_score`。SQLite 或 mock embedding 下使用平台侧相似度兜底；PostgreSQL 且查询 embedding 带 `vector` 时，会优先使用 pgvector `<=>` cosine 距离排序。默认 provider 是 `mock`，生产可设置：

```bash
export NEXA_EMBEDDING_PROVIDER=openai
export NEXA_OPENAI_API_KEY=<openai_api_key>
export NEXA_EMBEDDING_MODEL=text-embedding-3-small
export NEXA_EMBEDDING_DIMENSIONS=1536
```

OpenAI provider 会调用官方 `POST /embeddings` 接口，发送 `model`、`input`、`dimensions`。在 PostgreSQL 环境下，知识片段和用户记忆的 OpenAI vector 会同步写入 pgvector 列；切换 provider/model/dimensions 后，可用 `/api/embeddings/rebuild` 重建旧数据。

批量重建 embedding：

```http
POST /api/embeddings/rebuild
```

用于切换 embedding provider、model 或 dimensions 后重算旧数据。同步模式适合小范围重建，队列模式适合生产批量任务。

请求示例：

```json
{
  "target": "all",
  "run_mode": "sync",
  "source_id": 12,
  "user_id": 34,
  "limit": 1000,
  "force": true
}
```

字段说明：

- `target`: `all`、`knowledge` 或 `memory`。
- `run_mode`: `sync` 或 `queued`。
- `source_id`: 可选，只重建某个知识来源下的 chunks。
- `user_id`: 可选，只重建某个用户的长期记忆。
- `limit`: 可选，默认 `1000`，最大 `10000`。
- `force`: 可选，默认 `true`；传 `false` 时只补缺失或配置不一致的 embedding。

返回示例：

```json
{
  "status": "completed",
  "run_mode": "sync",
  "target": "all",
  "source_id": 12,
  "user_id": 34,
  "limit": 1000,
  "force": true,
  "processed": 2,
  "knowledge_chunks": 1,
  "memory_items": 1,
  "embedding_provider": "mock",
  "embedding_model": "text-embedding-3-small",
  "embedding_dimensions": 1536,
  "task_id": ""
}
```

队列模式返回 `status=queued` 和 `task_id`，由 worker 消费 `embedding.rebuild` 任务：

```bash
python -m app.worker once 20
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
GET /api/training/runs/{run_id}/quality-report
```

训练详情会额外返回 `quality_events`，用于展示该训练运行最近的质检审计记录。事件也会进入全局 `/api/security/audit-events`：

- `training_quality_passed`：质检通过并发布。
- `training_quality_blocked`：发布被质检阻断。
- `training_quality_override`：管理员带 `override_quality_gate=true` 强制发布。

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

发布前建议先读取 `quality-report`。质检报告会检查草稿 chunks 的高风险词、绝对化承诺、医疗/法律/投资风险、低置信度和过短正文：

```json
{
  "run_id": 12,
  "status": "blocked",
  "can_publish": false,
  "override": false,
  "metrics": {
    "draft_count": 1,
    "blocker_count": 2,
    "warning_count": 0,
    "average_confidence": 0.93
  },
  "issues": [
    {
      "code": "absolute_claim",
      "severity": "blocker",
      "message": "避免绝对化、宿命论或确定性承诺。",
      "chunk_id": 34,
      "chunk_title": "高风险承诺规则",
      "matches": ["一定会"]
    }
  ]
}
```

`status=blocked` 时，普通发布会返回 `400`，`detail` 以 `训练质检未通过：...` 开头。管理员确认后仍要强制发布，可以在发布 payload 中传：

```json
{
  "title": "AI 训练发布：月亮规则",
  "override_quality_gate": true,
  "operator": "qa"
}
```

发布后会创建 `source_type=ai_training` 的正式知识源，并进入 `/api/knowledge/search` 检索环境。发布响应会带回本次 `quality_report` 和 `quality_events`，方便后台审计展示。

知识库推荐标签体系：

```http
GET /api/knowledge/taxonomy
```

当前返回占星和八字两套推荐维度，供后台训练中心、手工录入和后续上传流程直接复用。

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

触发一次盘面计算 / 回写：

```http
POST /api/app/users/{user_id}/chart/calculate
```

当前支持三种模式：

- `simulate_algorithm_response`：联调用，直接把八字算法结果写回用户资料
- `NEXA_BAZI_CALC_MODE=live`：调用真实八字算法服务
- 默认：不调远程，直接返回当前快照

真实服务预留环境变量：

- `NEXA_BAZI_CALC_MODE`
- `NEXA_BAZI_API_URL`
- `NEXA_BAZI_API_TOKEN`
- `NEXA_BAZI_REQUEST_TIMEOUT_SECONDS`

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
