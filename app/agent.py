from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ChatMessage
from app.agent_tools import SYSTEM_TOOL_MAP, execute_agent_tools
from app.services import (
    create_chat_session,
    generate_chat_reply,
    get_user_memory_settings,
    load_chat_session_model,
    normalize_tags,
    sse_event,
)


VALID_SYSTEMS = {"astrology", "bazi", "tarot", "liuyao", "synastry", "oracle", "hybrid_transit"}

SYSTEM_LABELS = {
    "astrology": "占星",
    "bazi": "八字",
    "tarot": "塔罗",
    "liuyao": "六爻",
    "synastry": "合盘",
    "oracle": "签文",
    "hybrid_transit": "八字+占星行运",
}

SYSTEM_ALIASES = {
    "astrology": "astrology",
    "占星": "astrology",
    "星盘": "astrology",
    "行运": "astrology",
    "bazi": "bazi",
    "八字": "bazi",
    "四柱": "bazi",
    "大运": "bazi",
    "流年": "bazi",
    "tarot": "tarot",
    "塔罗": "tarot",
    "抽牌": "tarot",
    "liuyao": "liuyao",
    "六爻": "liuyao",
    "起卦": "liuyao",
    "synastry": "synastry",
    "合盘": "synastry",
    "relationship": "synastry",
    "oracle": "oracle",
    "签文": "oracle",
    "神谕": "oracle",
    "hybrid": "hybrid_transit",
    "综合": "hybrid_transit",
}

PAGE_SYSTEM_MAP = {
    "birth-chart-reading": "astrology",
    "daily-horoscope": "astrology",
    "bazi-birth-reading": "bazi",
    "bazi-daily-reading": "bazi",
}

SYSTEM_KNOWLEDGE_TAGS = {
    "astrology": ["占星"],
    "bazi": ["八字"],
    "tarot": ["塔罗"],
    "liuyao": ["六爻"],
    "synastry": ["合盘", "关系"],
    "oracle": ["签文"],
    "hybrid_transit": ["八字", "占星"],
}


def normalize_agent_system(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered in SYSTEM_ALIASES:
        return SYSTEM_ALIASES[lowered]
    for keyword, system in SYSTEM_ALIASES.items():
        if keyword and keyword in raw:
            return system
    return lowered if lowered in VALID_SYSTEMS else ""


def normalize_entry_type(value: object) -> str:
    entry_type = str(value or "free_question").strip()
    return entry_type if entry_type in {"preset_question", "free_question"} else "free_question"


def entry_system_from_context(entry_context: dict) -> str:
    system = normalize_agent_system(entry_context.get("system") or entry_context.get("selected_system"))
    if system:
        return system
    page_slug = str(entry_context.get("page_slug") or "").strip()
    return PAGE_SYSTEM_MAP.get(page_slug, "")


def explicit_system_from_content(content: str) -> str:
    text = str(content or "")
    if any(phrase in text for phrase in ["综合八字行运和占星行运", "八字行运和占星行运", "一起分析", "综合分析"]):
        if "八字" in text and ("占星" in text or "星盘" in text):
            return "hybrid_transit"
    if any(phrase in text for phrase in ["只用八字", "用八字", "八字看", "按八字"]):
        return "bazi"
    if any(phrase in text for phrase in ["只用占星", "用占星", "星盘看", "按占星"]):
        return "astrology"
    if any(phrase in text for phrase in ["用塔罗", "塔罗看", "抽塔罗", "抽牌"]):
        return "tarot"
    if any(phrase in text for phrase in ["用六爻", "六爻看", "起六爻", "起卦"]):
        return "liuyao"
    if any(phrase in text for phrase in ["用合盘", "合盘看"]):
        return "synastry"
    if any(phrase in text for phrase in ["用签文", "抽签", "神谕"]):
        return "oracle"
    return ""


def auto_match_system(content: str, entry_context: dict) -> tuple[str, str]:
    text = str(content or "")
    if any(keyword in text for keyword in ["对方想法", "他现在怎么想", "她现在怎么想", "暧昧", "复合", "关系状态"]):
        return "tarot", "这是感情互动、对方想法或关系状态问题，更适合先用塔罗看当下状态。"
    if any(keyword in text for keyword in ["该不该", "要不要", "能不能成", "是否能成", "具体事情", "短期结果", "现实风险", "答应"]):
        return "liuyao", "这是具体事件决策问题，更适合用六爻看局势、风险和短期结果。"
    if any(keyword in text for keyword in ["合不合适", "长期关系", "亲密关系", "合作关系", "两个人"]):
        return "synastry", "这是两个人长期互动模式问题，更适合用合盘看关系结构。"
    if any(keyword in text for keyword in ["大运", "流年", "人生方向", "长期趋势", "事业财运", "今年事业"]):
        return "bazi", "这是长期趋势、事业财运或人生方向问题，更适合用八字看结构。"
    if any(keyword in text for keyword in ["性格", "自我认知", "心理模式", "关系模式"]):
        return "astrology", "这是自我认知或心理模式问题，更适合用占星看人格结构。"
    if any(keyword in text for keyword in ["今日提醒", "快速指引", "安抚", "一句话"]):
        return "oracle", "这是轻量提醒和方向感问题，适合用签文快速收束。"
    if any(keyword in text for keyword in ["最近", "近期", "不顺", "运势", "波动", "行运"]):
        entry_system = entry_system_from_context(entry_context)
        if entry_system in {"astrology", "bazi"}:
            return entry_system, "这是近期波动或行运影响问题，优先沿用当前入口的行运体系。"
        return "astrology", "这是近期波动或行运影响问题，先用占星行运给出节奏判断。"
    return "astrology", "问题没有明确指定占术，先用占星做基础判断，再根据需要推荐其他工具。"


def build_quick_actions(recommended_system: str, current_system: str = "") -> list[dict]:
    actions = []
    if recommended_system:
        actions.append(
            {
                "label": f"用{SYSTEM_LABELS.get(recommended_system, recommended_system)}看",
                "value": recommended_system,
                "action": {"type": "confirm_route", "payload": {"selected_system": recommended_system}},
            }
        )
    if current_system and current_system != recommended_system:
        actions.append(
            {
                "label": f"继续用{SYSTEM_LABELS.get(current_system, current_system)}",
                "value": current_system,
                "action": {"type": "confirm_route", "payload": {"selected_system": current_system}},
            }
        )
    for fallback in ["tarot", "astrology"]:
        if fallback not in {recommended_system, current_system}:
            actions.append(
                {
                    "label": f"用{SYSTEM_LABELS[fallback]}",
                    "value": fallback,
                    "action": {"type": "confirm_route", "payload": {"selected_system": fallback}},
                }
            )
        if len(actions) >= 3:
            break
    return actions[:3]


def preview_agent_route(payload: dict) -> dict:
    content = str(payload.get("content") or payload.get("preset_question") or "").strip()
    entry_type = normalize_entry_type(payload.get("entry_type"))
    entry_context = payload.get("entry_context") if isinstance(payload.get("entry_context"), dict) else {}
    entry_system = entry_system_from_context(entry_context)
    payload_system = normalize_agent_system(payload.get("selected_system"))
    confirmed = payload.get("confirmed_route") if isinstance(payload.get("confirmed_route"), dict) else {}
    confirmed_system = normalize_agent_system(confirmed.get("selected_system"))
    explicit_system = payload_system or explicit_system_from_content(content)

    if explicit_system:
        selected = explicit_system
        route_source = "user_explicit"
        reason = f"用户已明确指定使用{SYSTEM_LABELS.get(selected, selected)}。"
        return route_payload(entry_type, route_source, selected, selected, False, reason, [])

    if entry_type == "preset_question" and entry_system:
        reason = f"这是页面预设问题入口，首轮绑定当前页面的{SYSTEM_LABELS.get(entry_system, entry_system)}体系。"
        return route_payload(entry_type, "entry_context", entry_system, entry_system, False, reason, [])

    if confirmed_system:
        reason = f"用户已确认切换到{SYSTEM_LABELS.get(confirmed_system, confirmed_system)}。"
        return route_payload(entry_type, "user_confirmed", confirmed_system, confirmed_system, False, reason, [])

    recommended, reason = auto_match_system(content, entry_context)
    selected = recommended
    needs_confirmation = False
    quick_actions: list[dict] = []
    if entry_system and entry_system != recommended:
        selected = entry_system
        needs_confirmation = True
        quick_actions = build_quick_actions(recommended, entry_system)
        reason = f"{reason} 当前入口是{SYSTEM_LABELS.get(entry_system, entry_system)}，所以先不自动切换，等待用户确认。"
    return route_payload(entry_type, "auto_match", selected, recommended, needs_confirmation, reason, quick_actions)


def route_payload(
    entry_type: str,
    route_source: str,
    selected_system: str,
    recommended_system: str,
    needs_confirmation: bool,
    reason: str,
    quick_actions: list[dict],
) -> dict:
    return {
        "entry_type": entry_type,
        "route_source": route_source,
        "selected_system": selected_system,
        "recommended_system": recommended_system,
        "needs_confirmation": needs_confirmation,
        "reason": reason,
        "quick_actions": quick_actions,
    }


def create_agent_session(session: Session, payload: dict) -> dict | None:
    entry_type = normalize_entry_type(payload.get("entry_type"))
    entry_context = payload.get("entry_context") if isinstance(payload.get("entry_context"), dict) else {}
    active_system = normalize_agent_system(payload.get("selected_system")) or entry_system_from_context(entry_context)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata["agent"] = {
        "entry_type": entry_type,
        "entry_context": entry_context,
        "active_system": active_system,
        "last_route": {},
    }
    return create_chat_session(
        session,
        {
            "user_id": payload.get("user_id"),
            "title": payload.get("title") or entry_context.get("preset_question") or "Agent 咨询",
            "topic": "agent",
            "status": payload.get("status") or "active",
            "metadata": metadata,
        },
    )


def generate_agent_reply(session: Session, session_id: int, payload: dict) -> dict | None:
    chat_session = load_chat_session_model(session, session_id)
    if chat_session is None:
        return None
    metadata = chat_session.metadata_json or {}
    agent_meta = metadata.get("agent") if isinstance(metadata.get("agent"), dict) else {}
    route_payload_input = {
        **payload,
        "entry_type": payload.get("entry_type") or agent_meta.get("entry_type") or "free_question",
        "entry_context": payload.get("entry_context") if isinstance(payload.get("entry_context"), dict) else agent_meta.get("entry_context") or {},
    }
    route = preview_agent_route(route_payload_input)
    chat_payload = dict(payload)
    chat_payload["user_message_metadata"] = {
        **(payload.get("user_message_metadata") if isinstance(payload.get("user_message_metadata"), dict) else {}),
        "agent_route": route,
    }
    if not chat_payload.get("knowledge_tags"):
        chat_payload["knowledge_tags"] = SYSTEM_KNOWLEDGE_TAGS.get(route["selected_system"], [])
    memory_settings = get_user_memory_settings(session, chat_session.user_id) or {}
    memory_enabled = memory_settings.get("memory_enabled", True)
    personalization_enabled = memory_settings.get("personalization_enabled", True)
    if payload.get("memory_enabled") is False or memory_enabled is False:
        chat_payload["memory_extraction"] = False
    if payload.get("memory_context_enabled") is False or personalization_enabled is False:
        chat_payload["memory_context_enabled"] = False

    reply = generate_chat_reply(session, session_id, chat_payload)
    if reply is None:
        return None

    tool_calls = execute_agent_tools(route, payload, reply.get("context") or {})
    assistant_message_id = reply["assistant_message"]["id"]
    assistant_message = session.get(ChatMessage, assistant_message_id)
    if assistant_message is not None:
        assistant_message.metadata_json = {
            **(assistant_message.metadata_json or {}),
            "agent_route": route,
            "agent_tool_calls": tool_calls,
        }
    chat_session.metadata_json = {
        **metadata,
        "agent": {
            **agent_meta,
            "entry_type": route["entry_type"],
            "entry_context": route_payload_input["entry_context"],
            "active_system": route["selected_system"],
            "last_route": route,
        },
    }
    session.add(chat_session)
    session.commit()

    return {
        "session_id": session_id,
        "status": reply["status"],
        "answer": reply["answer"],
        "route": route,
        "tool_calls": tool_calls,
        "memory_used": [] if chat_payload.get("memory_context_enabled") is False else select_relevant_memory(reply.get("context") or {}, route),
        "recommendations": build_agent_recommendations(route),
        "messages": {
            "user_message_id": reply["user_message"]["id"],
            "assistant_message_id": reply["assistant_message"]["id"],
        },
        "memory_updates": reply.get("memory_updates") or {},
        "context": reply.get("context") or {},
        "meta": {
            "mode": reply.get("meta", {}).get("mode"),
            "provider": reply.get("meta", {}).get("provider") or {},
        },
    }


def stream_agent_reply_events(reply: dict):
    yield sse_event("route", reply.get("route") or {})
    for tool_call in reply.get("tool_calls") or []:
        yield sse_event("tool_call", tool_call)
    answer = reply.get("answer") or ""
    chunk_size = 12
    for start in range(0, len(answer), chunk_size):
        yield sse_event("delta", {"text": answer[start : start + chunk_size]})
    yield sse_event("recommendations", {"items": reply.get("recommendations") or []})
    yield sse_event("memory", reply.get("memory_updates") or {"created_count": 0, "items": [], "summary": None})
    yield sse_event(
        "done",
        {
            "session_id": reply.get("session_id"),
            "status": reply.get("status"),
            "messages": reply.get("messages") or {},
            "answer": answer,
        },
    )


def select_relevant_memory(context: dict, route: dict) -> list[dict]:
    memory = context.get("memory") or {}
    items = memory.get("items") or []
    selected_system = route.get("selected_system") or ""
    labels = {SYSTEM_LABELS.get(selected_system, selected_system), selected_system}
    relevant = []
    for item in items:
        tags = set(normalize_tags(item.get("tags") or []))
        content = str(item.get("content") or "")
        if tags & labels or any(label and label in content for label in labels):
            relevant.append(item)
        elif len(relevant) < 3 and item.get("importance", 0) >= 4:
            relevant.append(item)
        if len(relevant) >= 5:
            break
    return relevant


def build_agent_recommendations(route: dict) -> list[dict]:
    if not route.get("needs_confirmation"):
        return []
    recommended = route.get("recommended_system") or ""
    tool_name = SYSTEM_TOOL_MAP.get(recommended, "")
    if not recommended or not tool_name:
        return []
    return [
        {
            "type": "tool",
            "target": tool_name,
            "title": f"用{SYSTEM_LABELS.get(recommended, recommended)}继续看",
            "reason": route.get("reason") or "",
            "action": {"type": "confirm_route", "payload": {"selected_system": recommended}},
        }
    ]
