from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
APP_HEADERS = {"Authorization": "Bearer dev-app-token"}


def create_session() -> tuple[dict, dict]:
    user_response = client.post(
        "/api/app/users",
        headers=APP_HEADERS,
        json={"external_id": f"memory-user-{uuid4().hex}", "nickname": "max"},
    )
    assert user_response.status_code == 200
    user = user_response.json()
    session_response = client.post(
        "/api/app/chat/sessions",
        headers=APP_HEADERS,
        json={"user_id": user["id"], "title": "记忆抽取测试", "topic": "daily"},
    )
    assert session_response.status_code == 200
    return user, session_response.json()


def test_chat_reply_extracts_memory_items_and_updates_summary():
    user, chat_session = create_session()

    response = client.post(
        f"/api/app/chat/sessions/{chat_session['id']}/reply",
        headers=APP_HEADERS,
        json={
            "content": "我喜欢你先给结论再解释，最近我在推进一个合作，但很在意边界。",
            "simulate_model_response": "可以，先给结论：适合推进，但要把边界讲清楚。",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["memory_updates"]["created_count"] >= 2
    assert any(item["memory_type"] == "preference" for item in data["memory_updates"]["items"])
    assert any(item["memory_type"] == "current_state" for item in data["memory_updates"]["items"])
    assert "先给结论" in data["memory_updates"]["summary"]["summary"]

    memories = client.get(f"/api/app/users/{user['id']}/memories", headers=APP_HEADERS).json()
    assert memories["summary"]["summary"].startswith("用户")
    assert any("合作" in item["content"] for item in memories["items"])


def test_chat_reply_can_disable_auto_memory_extraction():
    user, chat_session = create_session()

    response = client.post(
        f"/api/app/chat/sessions/{chat_session['id']}/reply",
        headers=APP_HEADERS,
        json={
            "content": "我喜欢短回复。",
            "simulate_model_response": "好的。",
            "memory_extraction": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["memory_updates"]["created_count"] == 0

    memories = client.get(f"/api/app/users/{user['id']}/memories", headers=APP_HEADERS).json()
    assert memories["summary"] is None
    assert memories["items"] == []


def test_chat_stream_also_extracts_memory_after_completion():
    user, chat_session = create_session()

    with client.stream(
        "GET",
        f"/api/app/chat/sessions/{chat_session['id']}/stream",
        headers=APP_HEADERS,
        params={
            "content": "最近我和伴侣沟通比较紧张，希望回答更温和一点。",
            "simulate_model_response": "可以，我会更温和地回应。",
        },
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    assert "event: memory" in body
    memories = client.get(f"/api/app/users/{user['id']}/memories", headers=APP_HEADERS).json()
    assert any(item["memory_type"] == "relationship" for item in memories["items"])
    assert "温和" in memories["summary"]["summary"]


def test_chat_reply_can_queue_memory_summary_until_worker_runs(monkeypatch):
    from app.core.settings import get_settings
    from app.platform.runtime import reset_platform_runtime
    from app.worker import process_next_task

    monkeypatch.setenv("NEXA_TASK_QUEUE_BACKEND", "memory")
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        user, chat_session = create_session()

        response = client.post(
            f"/api/app/chat/sessions/{chat_session['id']}/reply",
            headers=APP_HEADERS,
            json={
                "content": "我喜欢你先给结论再解释，最近我在推进一个合作，但很在意边界。",
                "simulate_model_response": "可以，先给结论：适合推进，但要把边界讲清楚。",
                "memory_run_mode": "queued",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["memory_updates"]["created_count"] >= 2
        assert data["memory_updates"]["summary_status"] == "queued"
        assert data["memory_updates"]["task_id"].startswith("task_")
        assert data["memory_updates"]["summary"] is None

        pending = client.get(f"/api/app/users/{user['id']}/memories", headers=APP_HEADERS).json()
        assert pending["summary"] is None
        assert any("合作" in item["content"] for item in pending["items"])

        assert process_next_task() is True

        after = client.get(f"/api/app/users/{user['id']}/memories", headers=APP_HEADERS).json()
        assert after["summary"] is not None
        assert "先给结论" in after["summary"]["summary"]
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()


def test_chat_stream_can_queue_memory_summary_until_worker_runs(monkeypatch):
    from app.core.settings import get_settings
    from app.platform.runtime import reset_platform_runtime
    from app.worker import process_next_task

    monkeypatch.setenv("NEXA_TASK_QUEUE_BACKEND", "memory")
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        user, chat_session = create_session()

        with client.stream(
            "GET",
            f"/api/app/chat/sessions/{chat_session['id']}/stream",
            headers=APP_HEADERS,
            params={
                "content": "最近我和伴侣沟通比较紧张，希望回答更温和一点。",
                "simulate_model_response": "可以，我会更温和地回应。",
                "memory_run_mode": "queued",
            },
        ) as response:
            assert response.status_code == 200
            body = response.read().decode("utf-8")

        assert "event: memory" in body
        assert '"summary_status": "queued"' in body

        pending = client.get(f"/api/app/users/{user['id']}/memories", headers=APP_HEADERS).json()
        assert pending["summary"] is None
        assert any(item["memory_type"] == "relationship" for item in pending["items"])

        assert process_next_task() is True

        after = client.get(f"/api/app/users/{user['id']}/memories", headers=APP_HEADERS).json()
        assert after["summary"] is not None
        assert "温和" in after["summary"]["summary"]
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()
