from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
APP_HEADERS = {"Authorization": "Bearer dev-app-token"}


def create_agent_user() -> dict:
    response = client.post(
        "/api/app/users",
        headers=APP_HEADERS,
        json={"external_id": f"agent-user-{uuid4().hex}", "nickname": "max", "timezone": "Asia/Shanghai"},
    )
    assert response.status_code == 200
    return response.json()


def create_agent_session(user_id: int, entry_type: str = "free_question", entry_context: dict | None = None) -> dict:
    response = client.post(
        "/api/app/agent/sessions",
        headers=APP_HEADERS,
        json={
            "user_id": user_id,
            "entry_type": entry_type,
            "entry_context": entry_context or {},
            "title": "Agent 咨询",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_agent_route_preview_respects_user_explicit_system():
    response = client.post(
        "/api/app/agent/route-preview",
        headers=APP_HEADERS,
        json={"content": "只用八字看我今年事业", "entry_type": "free_question"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["route_source"] == "user_explicit"
    assert data["selected_system"] == "bazi"
    assert data["recommended_system"] == "bazi"
    assert data["needs_confirmation"] is False


def test_agent_tools_registry_lists_connected_and_placeholder_tools():
    response = client.get("/api/app/agent/tools", headers=APP_HEADERS)

    assert response.status_code == 200
    items = response.json()["items"]
    by_name = {item["tool_name"]: item for item in items}
    assert by_name["astrology_birth_chart"]["provider_status"] == "connected_context"
    assert by_name["bazi_birth_chart"]["provider_status"] == "connected_context"
    assert by_name["tarot_reading"]["provider_status"] == "provider_placeholder"
    assert by_name["relationship_synastry"]["requires_relation_profile"] is True


def test_agent_route_preview_binds_preset_question_to_entry_system():
    response = client.post(
        "/api/app/agent/route-preview",
        headers=APP_HEADERS,
        json={
            "content": "这对我有什么影响？",
            "entry_type": "preset_question",
            "entry_context": {"page_slug": "daily-horoscope", "system": "astrology"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["route_source"] == "entry_context"
    assert data["selected_system"] == "astrology"
    assert data["needs_confirmation"] is False


def test_agent_route_preview_requires_confirmation_when_free_question_switches_entry_system():
    response = client.post(
        "/api/app/agent/route-preview",
        headers=APP_HEADERS,
        json={
            "content": "我该不该答应朋友这个具体事情？",
            "entry_type": "free_question",
            "entry_context": {"system": "astrology"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["route_source"] == "auto_match"
    assert data["selected_system"] == "astrology"
    assert data["recommended_system"] == "liuyao"
    assert data["needs_confirmation"] is True
    assert data["quick_actions"][0]["value"] == "liuyao"


def test_agent_session_stores_entry_context_in_metadata():
    user = create_agent_user()

    response = client.post(
        "/api/app/agent/sessions",
        headers=APP_HEADERS,
        json={
            "user_id": user["id"],
            "entry_type": "preset_question",
            "entry_context": {"page_slug": "daily-horoscope", "system": "astrology"},
            "title": "这对我有什么影响？",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["topic"] == "agent"
    assert data["metadata"]["agent"]["entry_type"] == "preset_question"
    assert data["metadata"]["agent"]["entry_context"]["system"] == "astrology"
    assert data["metadata"]["agent"]["active_system"] == "astrology"


def test_agent_reply_returns_route_metadata_tool_calls_and_message_ids():
    user = create_agent_user()
    agent_session = create_agent_session(user["id"], entry_type="free_question")

    response = client.post(
        f"/api/app/agent/sessions/{agent_session['id']}/reply",
        headers=APP_HEADERS,
        json={"content": "他现在怎么想我？", "simulate_model_response": "更适合先用塔罗看当下状态。"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["answer"] == "更适合先用塔罗看当下状态。"
    assert data["route"]["selected_system"] == "tarot"
    assert data["route"]["route_source"] == "auto_match"
    assert data["messages"]["user_message_id"]
    assert data["messages"]["assistant_message_id"]
    assert data["tool_calls"][0]["tool_name"] == "tarot_reading"


def test_agent_reply_keeps_current_system_when_confirmation_required():
    user = create_agent_user()
    agent_session = create_agent_session(
        user["id"],
        entry_type="free_question",
        entry_context={"system": "astrology"},
    )

    response = client.post(
        f"/api/app/agent/sessions/{agent_session['id']}/reply",
        headers=APP_HEADERS,
        json={"content": "我该不该答应朋友这个具体事情？", "simulate_model_response": "可以先确认。"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["route"]["selected_system"] == "astrology"
    assert data["route"]["recommended_system"] == "liuyao"
    assert data["route"]["needs_confirmation"] is True
    assert data["route"]["quick_actions"][0]["label"] == "用六爻看"
    assert data["tool_calls"][0]["tool_name"] == "astrology_birth_chart"


def test_agent_bazi_tool_uses_saved_chart_snapshot():
    user = create_agent_user()
    save_response = client.put(
        f"/api/app/users/{user['id']}/birth-profile",
        headers=APP_HEADERS,
        json={
            "nickname": "max",
            "birth_date": "1989-09-29",
            "birth_time": "16:00",
            "birth_city": "兰州",
            "birth_timezone": "Asia/Shanghai",
            "chart_system": "bazi",
            "bazi_profile": {
                "year_pillar": "己巳",
                "month_pillar": "癸酉",
                "day_pillar": "乙丑",
                "hour_pillar": "甲申",
                "day_master": "乙木",
            },
        },
    )
    assert save_response.status_code == 200
    agent_session = create_agent_session(user["id"], entry_type="free_question")

    response = client.post(
        f"/api/app/agent/sessions/{agent_session['id']}/reply",
        headers=APP_HEADERS,
        json={"content": "只用八字看我今年事业", "simulate_model_response": "先稳住节奏。"},
    )

    assert response.status_code == 200
    call = response.json()["tool_calls"][0]
    assert call["tool_name"] == "bazi_birth_chart"
    assert call["data_source"] == "user_chart_snapshot"
    assert call["output_payload"]["chart_snapshot"]["day_master"] == "乙木"
    assert call["output_payload"]["chart_snapshot"]["pillars"]["year"] == "己巳"


def test_agent_tarot_tool_returns_provider_placeholder_state():
    user = create_agent_user()
    agent_session = create_agent_session(user["id"], entry_type="free_question")

    response = client.post(
        f"/api/app/agent/sessions/{agent_session['id']}/reply",
        headers=APP_HEADERS,
        json={"content": "用塔罗看他现在怎么想我？", "simulate_model_response": "先看当下互动。"},
    )

    assert response.status_code == 200
    call = response.json()["tool_calls"][0]
    assert call["tool_name"] == "tarot_reading"
    assert call["data_source"] == "v1_tool_protocol"
    assert call["output_payload"]["protocol_status"] == "awaiting_provider"
    assert call["status"] == "ok"
    assert call["error"] == ""


def test_agent_synastry_tool_requires_relation_profile():
    user = create_agent_user()
    agent_session = create_agent_session(user["id"], entry_type="free_question")

    response = client.post(
        f"/api/app/agent/sessions/{agent_session['id']}/reply",
        headers=APP_HEADERS,
        json={"content": "用合盘看我们两个人长期合不合适", "simulate_model_response": "需要先补对方资料。"},
    )

    assert response.status_code == 200
    call = response.json()["tool_calls"][0]
    assert call["tool_name"] == "relationship_synastry"
    assert call["status"] == "needs_input"
    assert call["error"] == "relation_profile_required"
    assert call["needs_relation_profile"] is True
    assert call["output_payload"]["protocol_status"] == "needs_relation_profile"


def test_agent_stream_emits_route_tool_delta_recommendations_memory_and_done_events():
    user = create_agent_user()
    agent_session = create_agent_session(user["id"], entry_type="free_question")

    with client.stream(
        "GET",
        f"/api/app/agent/sessions/{agent_session['id']}/stream",
        headers=APP_HEADERS,
        params={"content": "用塔罗看他现在怎么想我？", "simulate_model_response": "先看当下互动。"},
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    assert "event: route" in body
    assert "event: tool_call" in body
    assert "event: delta" in body
    assert "event: recommendations" in body
    assert "event: memory" in body
    assert "event: done" in body
    assert "tarot_reading" in body
    assert "先看当下互动" in body


def test_agent_stream_accepts_query_api_key_and_confirmed_system():
    user = create_agent_user()
    agent_session = create_agent_session(user["id"], entry_type="free_question")

    with client.stream(
        "GET",
        f"/api/app/agent/sessions/{agent_session['id']}/stream",
        params={
            "api_key": "dev-app-token",
            "content": "那就用六爻看",
            "confirmed_system": "liuyao",
            "simulate_model_response": "先按六爻判断这件事。",
        },
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    assert '"selected_system": "liuyao"' in body
    assert "liuyao_reading" in body
    assert "先按六爻判断这件事" in body


def test_agent_message_feedback_records_message_context():
    user = create_agent_user()
    agent_session = create_agent_session(user["id"], entry_type="free_question")
    reply_response = client.post(
        f"/api/app/agent/sessions/{agent_session['id']}/reply",
        headers=APP_HEADERS,
        json={"content": "用塔罗看他现在怎么想我？", "simulate_model_response": "先看当下互动。"},
    )
    assert reply_response.status_code == 200
    assistant_message_id = reply_response.json()["messages"]["assistant_message_id"]

    response = client.post(
        f"/api/app/agent/messages/{assistant_message_id}/feedback",
        headers=APP_HEADERS,
        json={
            "feedback_type": "like",
            "target_type": "recommendation",
            "target_id": "tarot_reading",
            "metadata": {"clicked_recommendation": "tarot_reading"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == user["id"]
    assert data["session_id"] == agent_session["id"]
    assert data["message_id"] == assistant_message_id
    assert data["feedback_type"] == "like"
    assert data["target_type"] == "recommendation"
    assert data["target_id"] == "tarot_reading"
    assert data["metadata"]["clicked_recommendation"] == "tarot_reading"


def test_agent_message_feedback_requires_existing_message():
    response = client.post(
        "/api/app/agent/messages/99999999/feedback",
        headers=APP_HEADERS,
        json={"feedback_type": "like"},
    )

    assert response.status_code == 404


def test_agent_reply_respects_user_memory_settings():
    user = create_agent_user()
    client.post(
        f"/api/app/users/{user['id']}/memories",
        headers=APP_HEADERS,
        json={"memory_type": "preference", "content": "用户喜欢先给结论。", "importance": 5},
    )
    settings_response = client.put(
        f"/api/app/users/{user['id']}/memory-settings",
        headers=APP_HEADERS,
        json={"memory_enabled": False, "personalization_enabled": False},
    )
    assert settings_response.status_code == 200
    agent_session = create_agent_session(user["id"], entry_type="free_question")

    response = client.post(
        f"/api/app/agent/sessions/{agent_session['id']}/reply",
        headers=APP_HEADERS,
        json={"content": "最近合作项目怎么推进？", "simulate_model_response": "先确认边界。"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["memory_used"] == []
    assert data["memory_updates"]["created_count"] == 0
    assert data["memory_updates"]["summary_status"] == "skipped"
