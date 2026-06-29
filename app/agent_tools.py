from __future__ import annotations

import hashlib


SYSTEM_TOOL_MAP = {
    "astrology": "astrology_birth_chart",
    "bazi": "bazi_birth_chart",
    "tarot": "tarot_reading",
    "liuyao": "liuyao_reading",
    "synastry": "relationship_synastry",
    "oracle": "oracle_reading",
    "hybrid_transit": "hybrid_transit_reading",
}

TOOL_SPECS = {
    "astrology_birth_chart": {
        "system": "astrology",
        "requires_birth_profile": True,
        "requires_relation_profile": False,
        "requires_paid_access": False,
    },
    "bazi_birth_chart": {
        "system": "bazi",
        "requires_birth_profile": True,
        "requires_relation_profile": False,
        "requires_paid_access": False,
    },
    "tarot_reading": {
        "system": "tarot",
        "requires_birth_profile": False,
        "requires_relation_profile": False,
        "requires_paid_access": False,
    },
    "liuyao_reading": {
        "system": "liuyao",
        "requires_birth_profile": False,
        "requires_relation_profile": False,
        "requires_paid_access": False,
    },
    "relationship_synastry": {
        "system": "synastry",
        "requires_birth_profile": True,
        "requires_relation_profile": True,
        "requires_paid_access": False,
    },
    "oracle_reading": {
        "system": "oracle",
        "requires_birth_profile": False,
        "requires_relation_profile": False,
        "requires_paid_access": False,
    },
    "hybrid_transit_reading": {
        "system": "hybrid_transit",
        "requires_birth_profile": True,
        "requires_relation_profile": False,
        "requires_paid_access": False,
    },
}

CONNECTED_CONTEXT_TOOLS = {"astrology_birth_chart", "bazi_birth_chart", "hybrid_transit_reading"}
LOCAL_PROVIDER_TOOLS = {"tarot_reading", "liuyao_reading", "oracle_reading", "relationship_synastry"}

TAROT_DECK = [
    {"name": "愚者", "keywords": ["开始", "开放", "试探"], "message": "先允许事情有新的可能，但不要跳过现实确认。"},
    {"name": "女祭司", "keywords": ["直觉", "观察", "隐情"], "message": "答案不适合催出来，先观察对方真实行动。"},
    {"name": "皇后", "keywords": ["滋养", "吸引", "关系"], "message": "柔和表达会比强推更容易让关系回到流动。"},
    {"name": "皇帝", "keywords": ["边界", "规则", "掌控"], "message": "把边界和责任说清楚，事情才不会失焦。"},
    {"name": "恋人", "keywords": ["选择", "关系", "对齐"], "message": "关键不只是喜欢，而是双方是否愿意对齐选择。"},
    {"name": "战车", "keywords": ["推进", "意志", "方向"], "message": "可以推进，但需要一个明确方向，而不是情绪性冲刺。"},
    {"name": "力量", "keywords": ["耐心", "安抚", "自控"], "message": "用稳定感处理张力，会比直接对抗更有效。"},
    {"name": "隐士", "keywords": ["沉淀", "距离", "复盘"], "message": "先把自己的真实需求看清，再决定是否靠近。"},
    {"name": "命运之轮", "keywords": ["转机", "变化", "周期"], "message": "局势正在变化，先保留弹性，不要一次定死。"},
    {"name": "正义", "keywords": ["公平", "事实", "平衡"], "message": "以事实和对等为准，不要只凭情绪判断。"},
    {"name": "节制", "keywords": ["调和", "节奏", "修复"], "message": "放慢一点，给双方一个重新调频的空间。"},
    {"name": "星星", "keywords": ["希望", "疗愈", "信任"], "message": "事情还有修复空间，但需要真实而持续的行动。"},
]

ORACLE_DRAWS = [
    {"title": "留白", "keyword": "暂停", "message": "今天不必急着解释所有事，先把注意力收回来。", "action": "给自己留十分钟安静时间。"},
    {"title": "开门", "keyword": "表达", "message": "有些门不是撞开的，是清楚表达后自然打开的。", "action": "说一句具体、可执行的真实需求。"},
    {"title": "定锚", "keyword": "稳定", "message": "外界信息会晃动你，但你的节奏可以先稳住。", "action": "先完成一件最小且确定的事。"},
    {"title": "照见", "keyword": "觉察", "message": "今天适合看见模式，而不是急着给自己下结论。", "action": "写下你反复遇到的一个情绪触发点。"},
    {"title": "顺流", "keyword": "调整", "message": "答案可能不在用力里，而在顺势微调里。", "action": "把计划缩小一档，让它更容易开始。"},
    {"title": "边界", "keyword": "保护", "message": "温柔不是没有边界，清楚也不等于冷漠。", "action": "拒绝一个会消耗你的模糊请求。"},
]

TRIGRAMS = [
    {"name": "乾", "element": "金", "image": "天"},
    {"name": "兑", "element": "金", "image": "泽"},
    {"name": "离", "element": "火", "image": "火"},
    {"name": "震", "element": "木", "image": "雷"},
    {"name": "巽", "element": "木", "image": "风"},
    {"name": "坎", "element": "水", "image": "水"},
    {"name": "艮", "element": "土", "image": "山"},
    {"name": "坤", "element": "土", "image": "地"},
]


def tool_name_for_system(system: str) -> str:
    return SYSTEM_TOOL_MAP.get(system or "", "astrology_birth_chart")


def list_agent_tools() -> list[dict]:
    items = []
    for tool_name, spec in TOOL_SPECS.items():
        provider_status = "provider_placeholder"
        if tool_name in CONNECTED_CONTEXT_TOOLS:
            provider_status = "connected_context"
        elif tool_name in LOCAL_PROVIDER_TOOLS:
            provider_status = "local_provider"
        items.append(
            {
                "tool_name": tool_name,
                "system": spec["system"],
                "requires_birth_profile": bool(spec["requires_birth_profile"]),
                "requires_relation_profile": bool(spec["requires_relation_profile"]),
                "requires_paid_access": bool(spec["requires_paid_access"]),
                "provider_status": provider_status,
                "output_contract": {
                    "status": ["ok", "needs_input", "error"],
                    "required_fields": [
                        "tool_name",
                        "system",
                        "input_payload",
                        "output_payload",
                        "status",
                        "error",
                        "data_source",
                    ],
                },
            }
        )
    return items


def execute_agent_tools(route: dict, payload: dict, context: dict) -> list[dict]:
    selected_system = route.get("selected_system") or "astrology"
    return [execute_agent_tool(tool_name_for_system(selected_system), route, payload, context)]


def execute_agent_tool(tool_name: str, route: dict, payload: dict, context: dict) -> dict:
    if tool_name == "astrology_birth_chart":
        return execute_chart_tool(tool_name, "astrology", route, payload, context)
    if tool_name == "bazi_birth_chart":
        return execute_chart_tool(tool_name, "bazi", route, payload, context)
    if tool_name == "hybrid_transit_reading":
        return execute_hybrid_tool(tool_name, route, payload, context)
    if tool_name == "relationship_synastry":
        return execute_synastry_tool(tool_name, route, payload, context)
    if tool_name == "tarot_reading":
        return execute_tarot_tool(tool_name, route, payload, context)
    if tool_name == "liuyao_reading":
        return execute_liuyao_tool(tool_name, route, payload, context)
    if tool_name == "oracle_reading":
        return execute_oracle_tool(tool_name, route, payload, context)
    return base_tool_call(tool_name, route, payload, context, status="error", error="unknown_tool")


def execute_chart_tool(tool_name: str, expected_system: str, route: dict, payload: dict, context: dict) -> dict:
    chart_snapshot = context.get("chart_snapshot") or {}
    birth_profile = context.get("birth_profile") or {}
    warnings = list(context.get("chart_warnings") or chart_snapshot.get("warnings") or [])
    has_snapshot = bool(chart_snapshot)
    system_type = chart_snapshot.get("system_type") or ""
    compatible = expected_system == system_type or system_type == "hybrid"
    if expected_system == "bazi":
        compatible = compatible and bool(chart_snapshot.get("day_master") or chart_snapshot.get("pillars"))
    if expected_system == "astrology":
        compatible = compatible and bool(chart_snapshot.get("sun_sign") or system_type == "astrology")
    if not has_snapshot or not compatible:
        return base_tool_call(
            tool_name,
            route,
            payload,
            context,
            status="needs_input",
            error="birth_profile_required",
            data_source="user_chart_snapshot",
            result_summary="需要先补充或计算本命资料，才能使用该工具生成结构化结果。",
            output_payload={"chart_snapshot": chart_snapshot, "birth_profile": birth_profile},
            warnings=warnings or ["当前用户缺少可用的本命资料快照。"],
        )
    return base_tool_call(
        tool_name,
        route,
        payload,
        context,
        status="ok",
        data_source="user_chart_snapshot",
        result_summary="已从用户保存的本命资料和盘面快照读取结构化结果。",
        output_payload={
            "chart_snapshot": chart_snapshot,
            "birth_profile": birth_profile,
            "calculation_level": chart_snapshot.get("calculation_level") or "",
        },
        warnings=warnings,
    )


def execute_hybrid_tool(tool_name: str, route: dict, payload: dict, context: dict) -> dict:
    chart_snapshot = context.get("chart_snapshot") or {}
    if not chart_snapshot:
        return base_tool_call(
            tool_name,
            route,
            payload,
            context,
            status="needs_input",
            error="birth_profile_required",
            data_source="user_chart_snapshot",
            result_summary="综合行运需要先有占星或八字基础资料。",
            output_payload={},
            warnings=["当前用户缺少可用的本命资料快照。"],
        )
    return base_tool_call(
        tool_name,
        route,
        payload,
        context,
        status="ok",
        data_source="user_chart_snapshot",
        result_summary="已读取用户基础盘面，综合分析会在回答编排层分开呈现占星和八字视角。",
        output_payload={"chart_snapshot": chart_snapshot, "birth_profile": context.get("birth_profile") or {}},
        warnings=context.get("chart_warnings") or chart_snapshot.get("warnings") or [],
    )


def execute_synastry_tool(tool_name: str, route: dict, payload: dict, context: dict) -> dict:
    relation_profile = relation_profile_from_payload(payload)
    if not relation_profile:
        return base_tool_call(
            tool_name,
            route,
            payload,
            context,
            status="needs_input",
            error="relation_profile_required",
            data_source="v1_tool_protocol",
            result_summary="合盘需要对方资料。用户未提供时，前端可引导补充对方出生信息，或改用塔罗看当下互动。",
            output_payload={"protocol_status": "needs_relation_profile"},
            warnings=["缺少关系对象资料。"],
        )
    chart_snapshot = context.get("chart_snapshot") or {}
    if not chart_snapshot:
        return base_tool_call(
            tool_name,
            route,
            payload,
            context,
            status="needs_input",
            error="birth_profile_required",
            data_source="user_chart_snapshot",
            result_summary="合盘需要先有用户自己的本命资料，再结合关系对象资料分析。",
            output_payload={"protocol_status": "needs_birth_profile", "relation_profile": relation_profile},
            warnings=["缺少用户本命资料。"],
        )
    output_payload = build_local_synastry_result(route, payload, context, relation_profile)
    return base_tool_call(
        tool_name,
        route,
        payload,
        context,
        status="ok",
        data_source="local_synastry_provider_v1",
        result_summary="已基于用户本命快照和关系对象资料生成本地合盘结构结果。",
        output_payload=output_payload,
        warnings=["本地合盘 provider 为 V1 结构化分析，不替代专业完整合盘。"],
    )


def execute_tarot_tool(tool_name: str, route: dict, payload: dict, context: dict) -> dict:
    provided_result = provided_tool_result(payload, tool_name)
    if provided_result:
        return execute_provided_tool(tool_name, route, payload, context, provided_result)
    output_payload = build_local_tarot_result(route, payload, context)
    return base_tool_call(
        tool_name,
        route,
        payload,
        context,
        status="ok",
        data_source="local_tarot_provider_v1",
        result_summary="已完成本地三张牌抽取，返回可供回答编排使用的结构化牌阵。",
        output_payload=output_payload,
        warnings=["本地塔罗 provider 使用确定性抽取，适合联调和轻量体验。"],
    )


def execute_liuyao_tool(tool_name: str, route: dict, payload: dict, context: dict) -> dict:
    provided_result = provided_tool_result(payload, tool_name)
    if provided_result:
        return execute_provided_tool(tool_name, route, payload, context, provided_result)
    output_payload = build_local_liuyao_result(route, payload, context)
    return base_tool_call(
        tool_name,
        route,
        payload,
        context,
        status="ok",
        data_source="local_liuyao_provider_v1",
        result_summary="已完成本地六爻起卦结构生成，返回六爻线位、动爻和卦象摘要。",
        output_payload=output_payload,
        warnings=["本地六爻 provider 为简化起卦结构，后续可替换专业排盘算法。"],
    )


def execute_oracle_tool(tool_name: str, route: dict, payload: dict, context: dict) -> dict:
    provided_result = provided_tool_result(payload, tool_name)
    if provided_result:
        return execute_provided_tool(tool_name, route, payload, context, provided_result)
    output_payload = build_local_oracle_result(route, payload, context)
    return base_tool_call(
        tool_name,
        route,
        payload,
        context,
        status="ok",
        data_source="local_oracle_provider_v1",
        result_summary="已完成本地签文抽取，返回标题、关键词、提醒和行动建议。",
        output_payload=output_payload,
        warnings=["签文用于轻量提醒，不替代现实决策。"],
    )


def execute_provided_tool(tool_name: str, route: dict, payload: dict, context: dict, provided_result: dict) -> dict:
    return base_tool_call(
        tool_name,
        route,
        payload,
        context,
        status="ok",
        data_source="provided_tool_input",
        result_summary="已使用前端或上游传入的结构化工具结果。",
        output_payload={"protocol_status": "provided", "result": provided_result},
        warnings=[],
    )


def execute_protocol_placeholder_tool(tool_name: str, route: dict, payload: dict, context: dict) -> dict:
    provided_result = provided_tool_result(payload, tool_name)
    if provided_result:
        return execute_provided_tool(tool_name, route, payload, context, provided_result)
    return base_tool_call(
        tool_name,
        route,
        payload,
        context,
        status="ok",
        data_source="v1_tool_protocol",
        result_summary="V1 已确定工具协议边界，真实 provider 接入后会填充结构化结果。",
        output_payload={"protocol_status": "awaiting_provider"},
        warnings=["真实工具 provider 后续接入；当前不编造抽牌、卦象或签文结果。"],
    )


def build_local_tarot_result(route: dict, payload: dict, context: dict) -> dict:
    seed = stable_seed("tarot", payload.get("content"), route.get("selected_system"), user_seed(context))
    positions = ["现状", "阻力", "建议"]
    selected_indexes = unique_indexes(seed, len(TAROT_DECK), len(positions))
    cards = []
    for index, deck_index in enumerate(selected_indexes):
        card = TAROT_DECK[deck_index]
        orientation = "upright" if deterministic_int(seed, index + 7, 100) >= 28 else "reversed"
        cards.append(
            {
                "position": positions[index],
                "name": card["name"],
                "orientation": orientation,
                "keywords": card["keywords"],
                "message": card["message"] if orientation == "upright" else f"这张牌逆位提醒：先处理{card['keywords'][0]}里的卡点。",
            }
        )
    focus = detect_focus(payload.get("content"))
    return {
        "protocol_status": "computed",
        "provider": "local_tarot_provider_v1",
        "spread_type": "three_card",
        "focus": focus,
        "cards": cards,
        "synthesis": {
            "summary": f"本轮塔罗重点落在{focus_label(focus)}，适合先看现状、阻力和下一步动作。",
            "next_action": cards[-1]["message"],
        },
    }


def build_local_liuyao_result(route: dict, payload: dict, context: dict) -> dict:
    seed = stable_seed("liuyao", payload.get("content"), route.get("selected_system"), user_seed(context))
    line_names = ["初爻", "二爻", "三爻", "四爻", "五爻", "上爻"]
    line_kinds = [
        {"name": "少阴", "yin_yang": "yin", "moving": False},
        {"name": "少阳", "yin_yang": "yang", "moving": False},
        {"name": "老阴", "yin_yang": "yin", "moving": True},
        {"name": "老阳", "yin_yang": "yang", "moving": True},
    ]
    lines = []
    for index, line_name in enumerate(line_names):
        kind = line_kinds[deterministic_int(seed, index, len(line_kinds))]
        lines.append({"position": index + 1, "label": line_name, **kind})
    lower = TRIGRAMS[deterministic_int(seed, 9, len(TRIGRAMS))]
    upper = TRIGRAMS[deterministic_int(seed, 11, len(TRIGRAMS))]
    moving_lines = [line["position"] for line in lines if line["moving"]]
    if not moving_lines:
        moving_lines = [deterministic_int(seed, 13, 6) + 1]
        lines[moving_lines[0] - 1]["moving"] = True
        lines[moving_lines[0] - 1]["name"] = "老阳" if lines[moving_lines[0] - 1]["yin_yang"] == "yang" else "老阴"
    focus = detect_focus(payload.get("content"))
    return {
        "protocol_status": "computed",
        "provider": "local_liuyao_provider_v1",
        "method": "deterministic_question_seed",
        "question": str(payload.get("content") or ""),
        "hexagram": {
            "name": f"{upper['name']}上{lower['name']}下",
            "upper_trigram": upper,
            "lower_trigram": lower,
            "lines": lines,
            "moving_lines": moving_lines,
        },
        "judgement": {
            "focus": focus,
            "summary": "先看动爻所在位置，再判断推进节奏和现实条件。",
            "risk_hint": "若动爻集中在下三爻，先处理基础条件；若集中在上三爻，先观察外部反馈。",
        },
    }


def build_local_oracle_result(route: dict, payload: dict, context: dict) -> dict:
    seed = stable_seed("oracle", payload.get("content"), route.get("selected_system"), user_seed(context))
    draw = dict(ORACLE_DRAWS[deterministic_int(seed, 0, len(ORACLE_DRAWS))])
    return {
        "protocol_status": "computed",
        "provider": "local_oracle_provider_v1",
        "draw": draw,
        "ritual": {
            "duration_seconds": 30,
            "prompt": "先深呼吸一次，再把这个提醒落到一个具体小动作里。",
        },
    }


def build_local_synastry_result(route: dict, payload: dict, context: dict, relation_profile: dict) -> dict:
    chart_snapshot = context.get("chart_snapshot") or {}
    seed = stable_seed("synastry", payload.get("content"), user_seed(context), relation_profile)
    dimension_names = [
        ("communication", "沟通节奏"),
        ("emotional_safety", "情绪安全"),
        ("growth_rhythm", "成长节奏"),
        ("practical_support", "现实支持"),
    ]
    dimensions = []
    for index, (key, label) in enumerate(dimension_names):
        score = 45 + deterministic_int(seed, index, 46)
        dimensions.append({"key": key, "label": label, "score": score, "note": compatibility_note(score)})
    total_score = round(sum(item["score"] for item in dimensions) / len(dimensions))
    return {
        "protocol_status": "computed",
        "provider": "local_synastry_provider_v1",
        "method": "profile_and_chart_snapshot_v1",
        "relation_profile": relation_profile,
        "user_chart_snapshot": chart_snapshot,
        "compatibility": {
            "score": total_score,
            "level": compatibility_level(total_score),
            "dimensions": dimensions,
            "summary": "V1 先用双方资料做结构化关系画像，完整相位/宫位合盘后续可接专业算法。",
        },
    }


def base_tool_call(
    tool_name: str,
    route: dict,
    payload: dict,
    context: dict,
    status: str,
    error: str = "",
    data_source: str = "v1_tool_protocol",
    result_summary: str = "",
    output_payload: dict | None = None,
    warnings: list[str] | None = None,
) -> dict:
    spec = TOOL_SPECS.get(tool_name, {})
    system = spec.get("system") or route.get("selected_system") or ""
    input_payload = {
        "content": str(payload.get("content") or ""),
        "entry_type": route.get("entry_type") or "",
        "route_source": route.get("route_source") or "",
    }
    if relation_profile_from_payload(payload):
        input_payload["relation_profile"] = relation_profile_from_payload(payload)
    return {
        "tool_name": tool_name,
        "system": system,
        "input_payload": input_payload,
        "input_required": {
            "content": bool(input_payload["content"]),
            "birth_profile": bool(spec.get("requires_birth_profile")),
            "relation_profile": bool(spec.get("requires_relation_profile")),
        },
        "data_source": data_source,
        "needs_birth_info": bool(spec.get("requires_birth_profile")),
        "needs_relation_profile": bool(spec.get("requires_relation_profile")),
        "needs_paid_access": bool(spec.get("requires_paid_access")),
        "result_summary": result_summary,
        "raw_structured_result": {
            "route": route,
            "context_user_id": ((context.get("user") or {}).get("id") if isinstance(context.get("user"), dict) else None),
            "protocol_status": (output_payload or {}).get("protocol_status", "connected_context"),
        },
        "output_payload": output_payload or {},
        "confidence_or_warnings": warnings or [],
        "status": status,
        "error": error,
    }


def relation_profile_from_payload(payload: dict) -> dict:
    relation_profile = payload.get("relation_profile")
    return relation_profile if isinstance(relation_profile, dict) else {}


def user_seed(context: dict) -> str:
    user = context.get("user") if isinstance(context.get("user"), dict) else {}
    return str(user.get("id") or user.get("external_id") or "")


def stable_seed(*parts: object) -> int:
    normalized = "|".join(stable_repr(part) for part in parts)
    return int(hashlib.sha256(normalized.encode("utf-8")).hexdigest(), 16)


def stable_repr(value: object) -> str:
    if isinstance(value, dict):
        items = [f"{key}:{stable_repr(value[key])}" for key in sorted(value)]
        return "{" + ",".join(items) + "}"
    if isinstance(value, list):
        return "[" + ",".join(stable_repr(item) for item in value) + "]"
    return str(value or "")


def deterministic_int(seed: int, offset: int, modulo: int) -> int:
    if modulo <= 0:
        return 0
    shifted = seed >> (offset * 5)
    return shifted % modulo


def unique_indexes(seed: int, pool_size: int, count: int) -> list[int]:
    indexes: list[int] = []
    offset = 0
    while len(indexes) < count and len(indexes) < pool_size:
        candidate = deterministic_int(seed, offset, pool_size)
        if candidate not in indexes:
            indexes.append(candidate)
        offset += 1
    return indexes


def detect_focus(content: object) -> str:
    text = str(content or "")
    if any(keyword in text for keyword in ["感情", "关系", "复合", "他", "她", "暧昧", "合不合适"]):
        return "relationship"
    if any(keyword in text for keyword in ["合作", "事业", "工作", "项目", "财运"]):
        return "career"
    if any(keyword in text for keyword in ["今天", "今日", "最近", "状态"]):
        return "daily"
    return "general"


def focus_label(focus: str) -> str:
    return {
        "relationship": "关系互动",
        "career": "事业合作",
        "daily": "当下状态",
        "general": "当前问题",
    }.get(focus, "当前问题")


def compatibility_note(score: int) -> str:
    if score >= 78:
        return "这一维度比较顺，可以作为关系里的支撑点。"
    if score >= 62:
        return "这一维度有基础，但需要稳定沟通来维持。"
    return "这一维度容易出现误解，适合提前说清期待。"


def compatibility_level(score: int) -> str:
    if score >= 78:
        return "high"
    if score >= 62:
        return "medium"
    return "needs_attention"


def provided_tool_result(payload: dict, tool_name: str) -> dict:
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    candidates = [
        tool_input.get(tool_name),
        payload.get("tool_result"),
        payload.get("tarot_result") if tool_name == "tarot_reading" else None,
        payload.get("liuyao_result") if tool_name == "liuyao_reading" else None,
        payload.get("oracle_result") if tool_name == "oracle_reading" else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}
