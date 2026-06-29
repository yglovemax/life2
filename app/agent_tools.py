from __future__ import annotations


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


def tool_name_for_system(system: str) -> str:
    return SYSTEM_TOOL_MAP.get(system or "", "astrology_birth_chart")


def list_agent_tools() -> list[dict]:
    items = []
    for tool_name, spec in TOOL_SPECS.items():
        items.append(
            {
                "tool_name": tool_name,
                "system": spec["system"],
                "requires_birth_profile": bool(spec["requires_birth_profile"]),
                "requires_relation_profile": bool(spec["requires_relation_profile"]),
                "requires_paid_access": bool(spec["requires_paid_access"]),
                "provider_status": "connected_context" if tool_name in CONNECTED_CONTEXT_TOOLS else "provider_placeholder",
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
    if tool_name in {"tarot_reading", "liuyao_reading", "oracle_reading"}:
        return execute_protocol_placeholder_tool(tool_name, route, payload, context)
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
    return base_tool_call(
        tool_name,
        route,
        payload,
        context,
        status="ok",
        data_source="provided_relation_profile",
        result_summary="已接收关系对象资料，V1 先输出合盘工具协议结果。",
        output_payload={"protocol_status": "awaiting_provider", "relation_profile": relation_profile},
        warnings=["真实合盘计算服务后续接入。"],
    )


def execute_protocol_placeholder_tool(tool_name: str, route: dict, payload: dict, context: dict) -> dict:
    provided_result = provided_tool_result(payload, tool_name)
    if provided_result:
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
