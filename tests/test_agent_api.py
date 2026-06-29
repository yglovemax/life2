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
