# Nexa 通用占卜 Agent PRD V1

日期：2026-06-29

状态：产品开发主文档

关联原始需求：

- `/Users/chenkai/Downloads/Nexa通用占卜Agent开发需求文档_V1.md`

关联现有系统：

- `docs/project-memory.md`
- `docs/feature-catalog.md`
- `docs/app-api.md`
- `docs/frontend-api-contract.md`
- `docs/backend-integration.md`

## 1. 产品背景

Nexa 已有八字、占星、日运、命盘、塔罗、六爻、合盘、签文等多种占卜内容和模块。当前产品的问题不是能力缺失，而是用户进入 App 后不一定知道应该打开哪个页面、使用哪个工具、如何把自己的问题转化为合适的占卜方式。

因此 V1 要新增一个统一的个人占卜 Agent。用户可以直接提问，Agent 根据入口、用户明确选择、问题类型和用户上下文，选择最合适的占卜工具，并调用现有模块/API 生成回答。

这个 Agent 不是替代 App 的所有页面，而是成为用户最主要的交互入口，并把分散的功能以对话方式组织起来。

## 2. 产品定位

Nexa Agent 是一个统一的超级占卜 AI。

用户看到的是一个统一的个人顾问；系统内部由多种专业能力组成：

- 八字能力
- 占星能力
- 塔罗能力
- 六爻能力
- 合盘能力
- 签文/神谕能力
- 用户记忆能力
- 功能与付费内容推荐能力

Agent 需要做到：

- 能判断用户问题适合哪种占卜方式。
- 能尊重用户明确指定的占术。
- 能根据页面入口默认使用当前页面体系。
- 能在建议切换占术时先解释，再让用户确认。
- 能调用结构化 API，而不是读取页面文本猜内容。
- 能使用记忆，但不过度使用记忆。
- 能推荐相关功能或付费内容，但不强行推销。

## 3. V1 目标

### 3.1 用户目标

- 用户可以像问一个个人顾问一样直接提问。
- 用户不需要理解所有功能入口，也能被引导到合适占术。
- 用户从某个页面进入时，Agent 能理解当前页面数据。
- 用户能明确要求只用八字、只用占星、用塔罗、用六爻等。
- 用户感觉 Agent 记得自己，但不会机械重复旧记忆。

### 3.2 业务目标

- 提高用户提问频率和留存。
- 提升核心功能使用率：塔罗、六爻、合盘、八字报告、占星报告等。
- 为后续付费报告、课程、练习、深度解读做自然承接。
- 降低用户在功能页之间迷路的成本。

### 3.3 技术目标

- 在现有 `life2` 后端上新增 Agent 编排层。
- 复用现有用户、聊天、记忆、模块渲染、知识库、算法库和模型路由。
- 对前端提供稳定的 Agent API。
- 将占术路由、工具调用、记忆筛选、推荐、反馈拆成可测试的服务模块。

## 4. V1 范围

### 4.1 V1 必须做

- 统一 Agent 会话与回复接口。
- 页面预设问题入口。
- 自由提问入口。
- 占术路由器。
- 占术切换确认机制。
- 八字、占星、塔罗、六爻、合盘、签文的工具注册与调用框架。
- 基于现有模块/API 的八字和占星调用。
- 塔罗、六爻、合盘、签文的 V1 占位工具协议。
- 记忆相关性筛选。
- 用户记忆控制：开启、关闭、查看、删除、不再记住。
- 用户反馈记录。
- 功能推荐与付费内容推荐策略。
- SSE 流式回答。
- 后台配置：占术路由规则、工具映射、推荐位、输出策略。
- 文档和前端接口合同。

### 4.2 V1 不做

- 多个导师人格。
- 完全自动跨所有占卜体系混合回答。
- 系统主动推荐八字行运 + 占星行运综合分析。
- 复杂长期人生时间线。
- 梦境记录系统。
- 练习完成情况的深度分析。
- 非占卜类客服复杂处理。
- 收费、订单、支付闭环。

说明：付费内容推荐需要做，但真实购买链路和权益系统后续再做。

## 5. 用户入口

Agent V1 有两类入口。

### 5.1 页面预设问题入口

页面上方或模块附近展示一个预设问题浮窗。用户点击后进入 Agent 对话。

示例：

- 今天适合做什么？
- 这对我有什么影响？
- 我的感情最近有什么变化？

规则：

- `entry_type=preset_question`
- 必须携带当前 `page_slug`。
- 建议携带当前 `module_slug`。
- 必须携带 `preset_question`。
- 首轮回答默认绑定当前页面对应占术。
- 首轮回答不主动切换到其他占术。
- 回答必须结合当前页面结构化数据。

示例：

- 用户在占星每日星象事件页点击“这对我有什么影响？”
- Agent 默认使用占星每日行运/星象内容回答。

### 5.2 自由提问入口

用户主动打开 Agent，自由输入问题。

规则：

- `entry_type=free_question`
- 当前入口只作为参考，不强制绑定。
- 系统根据问题自动判断最适合占术。
- 如果推荐占术与当前入口不同，不能直接切换。
- 必须先解释为什么建议切换，再返回快捷按钮让用户确认。

示例：

用户从占星首页进入，但问：

> 我该不该答应朋友，让我保荐一个人去学校当老师？

Agent 判断为具体事件决策，更适合六爻。此时返回：

- 当前建议：六爻
- 是否需要确认：是
- 解释：这是具体事件决策，比性格或运势分析更适合用六爻看局势、风险和结果。
- 快捷按钮：
  - 用六爻看
  - 用占星
  - 使用塔罗牌

## 6. 占术路由规则

占术路由器是 Agent V1 核心能力。

### 6.1 路由优先级

冲突时按以下顺序：

1. 用户明确要求
2. 页面预设问题入口
3. 用户已确认的切换选择
4. 自动匹配占术

### 6.2 用户明确要求

用户明确指定占术时必须遵守。

示例：

- 只用八字看。
- 只用占星看。
- 用塔罗看。
- 不要用占星。
- 综合八字行运和占星行运看一下。

路由结果：

- `route_source=user_explicit`
- `needs_confirmation=false`
- `selected_system=<用户指定体系>`

例外：

- 用户要求的能力当前不可用时，不能假装可用，需要说明能力状态，并给出可用替代方案。

### 6.3 页面预设问题入口

如果用户点击页面预设问题，默认绑定当前页面体系。

示例：

- 八字页面进入：默认八字。
- 占星页面进入：默认占星。
- 六爻结果页进入：结合当前卦象。

路由结果：

- `route_source=entry_context`
- `needs_confirmation=false`
- `selected_system=<页面绑定体系>`

### 6.4 用户确认的切换选择

如果上一轮 Agent 建议切换占术，并返回快捷按钮，用户点击后，本轮必须使用用户点击的体系。

路由结果：

- `route_source=user_confirmed`
- `needs_confirmation=false`
- `selected_system=<用户选择体系>`

### 6.5 自动匹配占术

自由提问且无明确指定时，系统按问题类型匹配。

| 问题类型 | 推荐占术 |
| --- | --- |
| 感情、暧昧、对方想法、关系状态 | 塔罗 |
| 最近运势、近期不顺、是不是行运影响、最近感情/事业/财运波动 | 当前入口行运体系优先 |
| 具体事件、是否答应、是否能成、短期结果、现实风险 | 六爻 |
| 性格、自我认知、心理模式、关系模式 | 占星 |
| 大运、流年、事业财运、人生方向、长期趋势 | 八字 |
| 两个人的长期关系、亲密关系、合作关系 | 合盘 |
| 今日提醒、快速指引、轻量情绪安抚 | 签文/神谕 |

### 6.6 行运问题规则

行运类问题包括：

- 最近怎么样？
- 最近为什么不顺？
- 是不是运势影响？
- 最近感情/事业/财运波动是不是和运势有关？

规则：

- 从占星行运入口进入：优先占星行运。
- 从八字行运入口进入：优先八字行运。
- 没有明确入口：根据问题自动判断。
- 可以推荐塔罗、六爻、合盘等入口，但不能主动推荐综合分析。
- 用户点击推荐入口后，本轮只用该入口对应占术。

### 6.7 综合分析规则

综合分析不是系统主动推荐功能。

V1 只允许一种综合分析：

- 八字行运 + 占星行运

只有用户明确要求时才能进入综合分析。

明确表达示例：

- 请综合八字行运和占星行运看。
- 用八字行运和占星行运一起分析。
- 综合分析一下最近的感情运势。

不算明确要求的示例：

- 我最近感情怎么样？
- 我最近是不是不顺？
- 最近运势如何？

综合分析输出结构：

1. 总体结论
2. 八字行运视角
3. 占星行运视角
4. 两套行运共同指向
5. 两套行运差异
6. 当前行动建议

## 7. Agent 回答要求

### 7.1 普通回答结构

普通回答建议结构：

1. 直接结论
2. 原因解释
3. 对用户当前状态的理解
4. 行动建议
5. 下一步推荐

### 7.2 表达要求

- 先回答用户真正关心的问题。
- 不要一上来堆专业术语。
- 使用术语时必须简短解释。
- 有情绪价值，但不能空泛安慰。
- 有行动建议。
- 可以引导继续追问。
- 可以推荐更合适的占卜工具。
- 可以推荐相关模块或付费报告，但不能生硬。

### 7.3 安全边界

Agent 不能：

- 承诺确定结果。
- 做医疗、法律、投资结论。
- 鼓励用户做高风险决定。
- 用宿命论表达压迫用户。
- 使用“必然”“一定”“百分百”等绝对化结论。

## 8. Agent 工具能力

Agent 不直接读取页面文字猜内容。页面展示内容来自 API，Agent 回答也调用同一套结构化 API。

### 8.1 V1 工具清单

| 工具 | 能力 | V1 状态 |
| --- | --- | --- |
| `bazi_birth_chart` | 八字命盘信息 | 接现有八字资料/模块 |
| `bazi_daily_transit` | 八字今日/月/年运势 | 日运先接现有模块，月/年先占位 |
| `astrology_birth_chart` | 占星本命盘信息 | 接现有占星资料/模块 |
| `astrology_daily_transit` | 占星每日行运/星象 | 接现有日运模块 |
| `relationship_synastry` | 合盘信息 | V1 工具协议 + 占位返回 |
| `liuyao_reading` | 六爻起卦和卦象解读 | V1 工具协议 + 占位返回 |
| `oracle_reading` | 签文/神谕结果 | V1 工具协议 + 占位返回 |
| `tarot_reading` | 塔罗入口或塔罗结果 | V1 工具协议 + 占位返回 |
| `user_memory` | 用户记忆数据 | 接现有记忆系统，增加相关性筛选 |
| `user_feedback` | 用户反馈数据 | 新增反馈记录 |
| `recommendation` | 功能/报告/课程/练习推荐 | 新增推荐策略 |

### 8.2 工具返回要求

每个工具必须定义：

- `tool_name`
- `system`
- `input_schema`
- `output_schema`
- `requires_birth_profile`
- `requires_relation_profile`
- `requires_paid_access`
- `data_source`
- `error_codes`

### 8.3 工具调用失败

工具失败时不能直接让模型编造。

返回策略：

- 出生资料缺失：引导用户补资料。
- 关系对象资料缺失：提示需要补对方信息或改用塔罗。
- 功能未接入：说明当前能力未开放，并提供替代工具。
- 付费权限缺失：给免费简版解释，再推荐付费报告。
- API 异常：使用 fallback，并记录审计/trace。

## 9. 记忆系统

### 9.1 V1 记录内容

Agent 需要记录：

- 基础出生信息。
- 历史问题主题。
- 用户情绪状态。
- 关系对象。
- 用户偏好。
- 点赞、点踩、分享。
- 多个 Agent/工具的聊天总结。

### 9.2 记忆使用规则

每次回答前，系统必须判断哪些记忆与当前问题有关。

不能把所有记忆都塞进回答里。

规则：

- 只取与当前问题主题、情绪、关系对象或占术相关的记忆。
- 默认最多使用 3-5 条记忆。
- 低相关记忆不进入 prompt。
- 使用记忆不等于必须明说记忆。
- 用户要求“不要记住”时，本轮不抽取记忆。
- 用户关闭记忆时，不读取个性化记忆，不新增记忆。

### 9.3 记忆不能反复明说

即使使用记忆，也不应该每次直接说：

> 因为你之前说过……

更合适的方式是：

- 调整语气。
- 调整建议颗粒度。
- 避免重复推荐用户拒绝过的内容。
- 在确实必要时才显式引用。

### 9.4 用户记忆控制

V1 需要提供：

- 开启/关闭记忆。
- 查看已保存记忆。
- 删除某条记忆。
- 要求 Agent 不再记住某件事。

## 10. 反馈系统

V1 需要记录以下反馈事件：

- 点赞。
- 点踩。
- 分享。
- 是否继续追问。
- 是否点击推荐模块。
- 是否购买付费内容。
- 是否完成推荐练习。
- 是否反复问同类问题。

反馈用途：

- 判断回答是否有效。
- 判断用户偏好占术。
- 判断用户关注主题。
- 判断推荐是否带来转化。
- 后续优化路由和推荐。

## 11. 推荐系统

Agent 可以推荐功能或付费内容。

可推荐内容：

- 塔罗占卜。
- 六爻起卦。
- 关系合盘。
- 八字完整报告。
- 占星完整报告。
- 今日签文。
- 课程/练习。
- 付费解读。

推荐规则：

- 必须和当前问题相关。
- 推荐前要解释为什么适合。
- 不要每次都推荐付费内容。
- 用户已拒绝时不要重复推荐。
- 推荐必须以行动按钮/结构化数据返回，不能只写在文本里。

推荐返回结构：

```json
{
  "recommendations": [
    {
      "type": "tool",
      "target": "tarot_reading",
      "title": "用塔罗看对方想法",
      "reason": "塔罗更适合看当下关系状态和对方态度。",
      "action": {
        "type": "start_tool",
        "payload": {"system": "tarot"}
      }
    }
  ]
}
```

## 12. API 需求

### 12.1 创建 Agent 会话

```http
POST /api/app/agent/sessions
```

Request：

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

Response：

```json
{
  "id": 100,
  "user_id": 1,
  "entry_type": "preset_question",
  "entry_context": {},
  "status": "active",
  "messages": []
}
```

### 12.2 Agent 回复

```http
POST /api/app/agent/sessions/{session_id}/reply
```

Request：

```json
{
  "content": "我最近感情一直不顺，是不是长期运势也不好？",
  "selected_system": "",
  "confirmed_route": null,
  "memory_enabled": true,
  "stream": false
}
```

Response：

```json
{
  "session_id": 100,
  "status": "ok",
  "answer": "最近你的感情状态更像是在观察和重新确认，而不是马上做决定。",
  "route": {
    "entry_type": "free_question",
    "route_source": "auto_match",
    "selected_system": "astrology_transit",
    "recommended_system": "astrology_transit",
    "needs_confirmation": false,
    "reason": "这是近期感情波动和行运影响问题，适合先从当前行运体系看。"
  },
  "tool_calls": [],
  "memory_used": [],
  "recommendations": [],
  "messages": {
    "user_message_id": 1,
    "assistant_message_id": 2
  },
  "meta": {
    "mode": "mock",
    "trace_id": "trace_agent_20260629_0001"
  }
}
```

### 12.3 Agent 流式回复

```http
GET /api/app/agent/sessions/{session_id}/stream
```

或：

```http
POST /api/app/agent/sessions/{session_id}/stream
```

SSE 事件：

- `route`
- `tool_call`
- `delta`
- `recommendations`
- `memory`
- `done`

### 12.4 占术路由预览

```http
POST /api/app/agent/route-preview
```

用途：

- 前端调试。
- 后台配置验证。
- 自动化测试。

Response：

```json
{
  "selected_system": "liuyao",
  "recommended_system": "liuyao",
  "needs_confirmation": true,
  "reason": "这是具体事件决策问题，更适合六爻。",
  "quick_actions": [
    {"label": "用六爻看", "value": "liuyao"},
    {"label": "用占星", "value": "astrology"},
    {"label": "使用塔罗牌", "value": "tarot"}
  ]
}
```

### 12.5 用户反馈

```http
POST /api/app/agent/messages/{message_id}/feedback
```

Request：

```json
{
  "feedback_type": "like",
  "metadata": {
    "clicked_recommendation": "tarot_reading"
  }
}
```

### 12.6 记忆控制

复用现有记忆接口，并新增或扩展：

```http
GET /api/app/users/{user_id}/memories
POST /api/app/users/{user_id}/memories
DELETE /api/app/users/{user_id}/memories/{memory_id}
PUT /api/app/users/{user_id}/memory-settings
```

## 13. 数据模型需求

### 13.1 AgentSession

可复用现有 `ChatSession`，但 V1 推荐增加 Agent 专用字段或通过 `metadata_json` 过渡。

字段：

- `id`
- `user_id`
- `entry_type`
- `entry_context`
- `active_system`
- `last_route`
- `status`
- `created_at`
- `updated_at`

### 13.2 AgentRouteDecision

字段：

- `id`
- `session_id`
- `message_id`
- `entry_type`
- `route_source`
- `selected_system`
- `recommended_system`
- `needs_confirmation`
- `reason`
- `quick_actions`
- `created_at`

### 13.3 AgentToolCall

字段：

- `id`
- `session_id`
- `message_id`
- `tool_name`
- `system`
- `input_payload`
- `output_payload`
- `status`
- `error`
- `created_at`

### 13.4 AgentFeedback

字段：

- `id`
- `user_id`
- `session_id`
- `message_id`
- `feedback_type`
- `target_type`
- `target_id`
- `metadata_json`
- `created_at`

### 13.5 MemorySettings

可放入 `AppUser.profile` 或独立表。

字段：

- `user_id`
- `memory_enabled`
- `personalization_enabled`
- `updated_at`

## 14. 后台配置需求

后台需要支持：

- 占术路由规则配置。
- 问题关键词与占术映射。
- 页面与默认占术绑定。
- 页面预设问题管理。
- Agent 工具注册表。
- 工具与模块/API 映射。
- 推荐内容配置。
- 反馈统计查看。
- Agent 调用 trace 查看。
- 记忆命中查看。

V1 后台可先做最小可用：

- 路由规则只读展示 + JSON 编辑。
- 工具注册表只读展示 + 手动启停。
- 推荐位 JSON 配置。
- Agent trace 列表。

## 15. 前端对接要求

### 15.1 页面预设入口

前端点击预设问题时必须传：

- `entry_type=preset_question`
- `page_slug`
- `module_slug`
- `system`
- `preset_question`
- 当前页面结构化数据或可重算标识

### 15.2 自由提问入口

前端打开 Agent 时建议传：

- `entry_type=free_question`
- 当前页面上下文，若有
- 用户输入内容

### 15.3 快捷按钮

当 `route.needs_confirmation=true` 时，前端必须展示 `quick_actions`。

用户点击后，下一轮请求带：

```json
{
  "confirmed_route": {
    "selected_system": "liuyao",
    "source_route_decision_id": 123
  }
}
```

### 15.4 推荐按钮

Agent 返回 `recommendations` 时，前端需要展示为可点击按钮或卡片，并在点击后上报反馈。

## 16. 验收标准

V1 验收必须满足：

1. 用户可以从首页浮窗进入 Agent 对话。
2. 用户可以从模块内按钮带当前页面上下文进入 Agent 对话。
3. 页面预设问题首轮默认使用当前页面体系。
4. 自由提问时，Agent 可以自动推荐合适占术。
5. 用户明确要求占术时，Agent 必须遵守。
6. 推荐占术和当前入口不一致时，Agent 必须先解释并让用户选择。
7. 用户明确要求综合八字行运 + 占星行运时，Agent 可以分层回答。
8. 用户没有明确要求综合分析时，Agent 不主动综合。
9. Agent 可以调用八字和占星现有模块/API。
10. Agent 对塔罗、六爻、合盘、签文提供 V1 工具协议和可用占位返回。
11. Agent 保存基础记忆和聊天总结。
12. Agent 不会把无关记忆塞进每次回答。
13. 用户可以关闭记忆、查看记忆、删除记忆。
14. Agent 可以记录点赞、点踩、分享、推荐点击等反馈。
15. Agent 可以推荐相关功能或付费内容，但不会每次强推。
16. SSE 流式回复可以输出路由、工具调用、文本、推荐和完成事件。
17. 后台可以查看 Agent trace、路由结果和工具调用记录。

## 17. 开发分期

### 17.1 Phase A：Agent 路由和会话闭环

- Agent session API。
- Agent reply API。
- Agent route preview API。
- 占术路由器。
- 页面入口上下文。
- 切换确认 quick actions。
- 单元测试覆盖路由优先级。

### 17.2 Phase B：工具编排

- Agent 工具注册表。
- 八字工具接现有页面/模块 API。
- 占星工具接现有页面/模块 API。
- 塔罗、六爻、合盘、签文占位工具。
- 工具调用记录。
- 工具失败 fallback。

### 17.3 Phase C：记忆和反馈

- 记忆相关性筛选。
- 记忆开关。
- 记忆删除。
- 反馈 API。
- 推荐点击记录。
- 反复问题主题统计。

### 17.4 Phase D：推荐系统和后台配置

- 推荐规则。
- 推荐内容配置。
- 路由规则后台配置。
- Agent trace 后台查看。
- 前端接口文档完善。

### 17.5 Phase E：生产增强

- Redis 队列化长任务。
- Postgres + pgvector 记忆检索验证。
- 模型成本统计接 Agent 维度。
- 更完整权限和付费接口预留。

## 18. 与现有系统关系

现有系统不是废弃，而是 Agent 的工具底座。

可复用能力：

- `/api/app/users`
- `/api/app/users/{user_id}/birth-profile`
- `/api/app/users/{user_id}/chart`
- `/api/app/pages/{page_slug}/render`
- `/api/app/modules/{module_slug}/render`
- `/api/app/chat/sessions`
- `/api/app/chat/sessions/{session_id}/reply`
- `/api/app/chat/sessions/{session_id}/stream`
- `/api/app/users/{user_id}/memories`
- `/api/knowledge/search`
- `/api/algorithms`
- 模型路由和输出策略
- 训练资料和知识库

新增 Agent 层负责：

- 入口理解。
- 占术路由。
- 切换确认。
- 工具选择。
- 记忆筛选。
- 推荐编排。
- 反馈闭环。

## 19. 风险和处理

| 风险 | 处理 |
| --- | --- |
| Agent 自动切错占术 | 加确认机制；首轮不强切；路由结果可解释 |
| 记忆过度使用 | 相关性筛选；限制条数；默认不明说记忆 |
| 工具能力未完整 | V1 提供工具协议和占位返回，不假装完整 |
| 回复过度玄学或绝对化 | 输出策略和质检规则继续生效 |
| 付费推荐太生硬 | 推荐必须有原因；拒绝后不重复推 |
| 前端和 Agent 数据不一致 | Agent 调同一套结构化 API，不读取页面文案 |

## 20. 一句话总结

Nexa 通用占卜 Agent V1 要在现有后端能力之上，新增统一 Agent 编排层，让用户可以直接提问，由系统根据入口、用户选择和问题类型调用最合适的八字、占星、塔罗、六爻、合盘、签文等能力，并以清晰、有帮助、有记忆但不过度打扰的方式回答用户。
