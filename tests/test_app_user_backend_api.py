from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
APP_HEADERS = {"Authorization": "Bearer dev-app-token"}


def create_user() -> dict:
    external_id = f"frontend-user-{uuid4().hex}"
    response = client.post(
        "/api/app/users",
        headers=APP_HEADERS,
        json={
            "external_id": external_id,
            "nickname": "max",
            "locale": "zh-CN",
            "timezone": "Asia/Shanghai",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_app_user_create_is_idempotent_by_external_id():
    external_id = f"wechat-openid-{uuid4().hex}"

    first = client.post(
        "/api/app/users",
        headers=APP_HEADERS,
        json={"external_id": external_id, "nickname": "max"},
    )
    second = client.post(
        "/api/app/users",
        headers=APP_HEADERS,
        json={"external_id": external_id, "nickname": "Max Updated"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["nickname"] == "Max Updated"


def test_birth_profile_save_and_chart_snapshot():
    user = create_user()

    save_response = client.put(
        f"/api/app/users/{user['id']}/birth-profile",
        headers=APP_HEADERS,
        json={
            "nickname": "max",
            "birth_date": "1989-09-29",
            "birth_time": "16:00",
            "birth_city": "兰州",
            "birth_country": "CN",
            "birth_timezone": "Asia/Shanghai",
        },
    )
    assert save_response.status_code == 200
    profile = save_response.json()
    assert profile["birth_date"] == "1989-09-29"
    assert profile["birth_city"] == "兰州"

    chart_response = client.get(f"/api/app/users/{user['id']}/chart", headers=APP_HEADERS)
    assert chart_response.status_code == 200
    chart = chart_response.json()
    assert chart["user_id"] == user["id"]
    assert chart["birth_profile"]["birth_time"] == "16:00"
    assert chart["chart_snapshot"]["sun_sign"] == "天秤座"
    assert chart["chart_snapshot"]["calculation_level"] == "sun_sign_only"
    assert chart["warnings"]


def test_birth_profile_save_supports_bazi_snapshot():
    user = create_user()

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
                "five_elements": {"wood": 2, "fire": 1, "earth": 2, "metal": 2, "water": 1},
                "ten_gods": ["比肩", "偏印"],
            },
        },
    )
    assert save_response.status_code == 200
    profile = save_response.json()
    assert profile["chart_system"] == "bazi"
    assert profile["bazi_profile"]["day_master"] == "乙木"

    chart_response = client.get(f"/api/app/users/{user['id']}/chart", headers=APP_HEADERS)
    assert chart_response.status_code == 200
    chart = chart_response.json()
    assert chart["chart_snapshot"]["system_type"] == "bazi"
    assert chart["chart_snapshot"]["calculation_level"] == "bazi_input_only"
    assert chart["chart_snapshot"]["day_master"] == "乙木"
    assert chart["chart_snapshot"]["pillars"]["year"] == "己巳"


def test_chat_session_records_messages_in_order():
    user = create_user()
    session_response = client.post(
        "/api/app/chat/sessions",
        headers=APP_HEADERS,
        json={"user_id": user["id"], "title": "今日咨询", "topic": "daily"},
    )
    assert session_response.status_code == 200
    session = session_response.json()

    user_message = client.post(
        f"/api/app/chat/sessions/{session['id']}/messages",
        headers=APP_HEADERS,
        json={"role": "user", "content": "今天适合推进合作吗？"},
    )
    assistant_message = client.post(
        f"/api/app/chat/sessions/{session['id']}/messages",
        headers=APP_HEADERS,
        json={"role": "assistant", "content": "适合先确认边界和节奏。", "metadata": {"model": "mock"}},
    )
    assert user_message.status_code == 200
    assert assistant_message.status_code == 200

    detail_response = client.get(f"/api/app/chat/sessions/{session['id']}", headers=APP_HEADERS)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["metadata"]["model"] == "mock"


def test_memory_summary_and_items_are_listed_for_user():
    user = create_user()

    summary_response = client.put(
        f"/api/app/users/{user['id']}/memory-summary",
        headers=APP_HEADERS,
        json={"summary": "用户偏好清晰直接的建议，关注合作和关系边界。"},
    )
    item_response = client.post(
        f"/api/app/users/{user['id']}/memories",
        headers=APP_HEADERS,
        json={
            "memory_type": "preference",
            "content": "用户喜欢先给结论再解释。",
            "tags": ["偏好", "表达"],
            "importance": 4,
        },
    )
    assert summary_response.status_code == 200
    assert item_response.status_code == 200

    list_response = client.get(f"/api/app/users/{user['id']}/memories", headers=APP_HEADERS)
    assert list_response.status_code == 200
    data = list_response.json()
    assert data["summary"]["summary"].startswith("用户偏好")
    assert data["items"][0]["memory_type"] == "preference"
    assert "表达" in data["items"][0]["tags"]
