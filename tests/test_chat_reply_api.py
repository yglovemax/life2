from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
APP_HEADERS = {"Authorization": "Bearer dev-app-token"}


def create_chat_user_with_context() -> tuple[dict, dict]:
    user_response = client.post(
        "/api/app/users",
        headers=APP_HEADERS,
        json={"external_id": f"chat-user-{uuid4().hex}", "nickname": "max", "timezone": "Asia/Shanghai"},
    )
    assert user_response.status_code == 200
    user = user_response.json()
    birth_response = client.put(
        f"/api/app/users/{user['id']}/birth-profile",
        headers=APP_HEADERS,
        json={
            "nickname": "max",
            "birth_date": "1989-09-29",
            "birth_time": "16:00",
            "birth_city": "兰州",
            "birth_timezone": "Asia/Shanghai",
        },
    )
    assert birth_response.status_code == 200
    client.put(
        f"/api/app/users/{user['id']}/memory-summary",
        headers=APP_HEADERS,
        json={"summary": "用户偏好直接、温和、有行动建议的回答。"},
    )
    client.post(
        f"/api/app/users/{user['id']}/memories",
        headers=APP_HEADERS,
        json={"memory_type": "preference", "content": "用户关注合作节奏和边界。", "tags": ["合作", "边界"], "importance": 5},
    )
    session_response = client.post(
        "/api/app/chat/sessions",
        headers=APP_HEADERS,
        json={"user_id": user["id"], "title": "今日咨询", "topic": "daily"},
    )
    assert session_response.status_code == 200
    return user, session_response.json()


def test_chat_reply_saves_user_and_assistant_messages_with_context():
    _, chat_session = create_chat_user_with_context()
    client.post(
        "/api/knowledge-sources",
        json={
            "title": "合作咨询规则",
            "source_type": "markdown",
            "content": "# 合作\n合作问题先看节奏、边界和对方反馈，不要一次性做重大承诺。",
            "tags": ["合作", "咨询规则"],
        },
    )

    response = client.post(
        f"/api/app/chat/sessions/{chat_session['id']}/reply",
        headers=APP_HEADERS,
        json={
            "content": "今天适合推进合作吗？",
            "knowledge_tags": ["合作"],
            "simulate_model_response": "可以推进，但先确认节奏、边界和对方反馈。",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["answer"] == "可以推进，但先确认节奏、边界和对方反馈。"
    assert data["user_message"]["role"] == "user"
    assert data["assistant_message"]["role"] == "assistant"
    assert data["context"]["chart_snapshot"]["sun_sign"] == "天秤座"
    assert data["context"]["memory"]["summary"]["summary"].startswith("用户偏好")
    assert data["context"]["knowledge_hits"]

    detail = client.get(f"/api/app/chat/sessions/{chat_session['id']}", headers=APP_HEADERS).json()
    assert [message["role"] for message in detail["messages"]][-2:] == ["user", "assistant"]


def test_chat_reply_mock_uses_context_when_no_model_response():
    _, chat_session = create_chat_user_with_context()

    response = client.post(
        f"/api/app/chat/sessions/{chat_session['id']}/reply",
        headers=APP_HEADERS,
        json={"content": "我今天要注意什么？"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "max" in data["answer"]
    assert "天秤座" in data["answer"]
    assert data["meta"]["mode"] == "mock"


def test_chat_stream_emits_sse_events_and_persists_assistant_message():
    _, chat_session = create_chat_user_with_context()

    with client.stream(
        "GET",
        f"/api/app/chat/sessions/{chat_session['id']}/stream",
        headers=APP_HEADERS,
        params={"content": "今天适合表达想法吗？", "simulate_model_response": "适合，但要先把重点说清楚。"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = response.read().decode("utf-8")

    assert "event: meta" in body
    assert "event: delta" in body
    assert "适合" in body
    assert "event: done" in body

    detail = client.get(f"/api/app/chat/sessions/{chat_session['id']}", headers=APP_HEADERS).json()
    assert detail["messages"][-1]["role"] == "assistant"
    assert "重点说清楚" in detail["messages"][-1]["content"]
