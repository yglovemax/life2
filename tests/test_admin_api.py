from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_reports_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_seeded_module_center_contains_phase_one_pages():
    response = client.get("/api/modules")
    assert response.status_code == 200
    data = response.json()

    page_names = {item["page_name"] for item in data["items"]}
    module_names = {item["name"] for item in data["items"]}

    assert "出生星盘解读页" in page_names
    assert "每日星座运势页" in page_names
    assert "星盘详解" in module_names
    assert "每日寄语" in module_names


def test_module_detail_exposes_prompt_contracts_and_trace_columns():
    list_response = client.get("/api/modules")
    module_id = list_response.json()["items"][0]["id"]

    response = client.get(f"/api/modules/{module_id}")
    assert response.status_code == 200
    data = response.json()

    assert "prompt" in data
    assert "fields" in data
    assert "recent_calls" in data
    assert set(data["prompt"]) >= {
        "shared_prefix",
        "module_rules",
        "algorithm_data_template",
        "user_preferences_template",
        "final_request_template",
    }
    assert data["fields"][0]["field_name"]


def test_test_run_creates_call_trace_with_final_json():
    list_response = client.get("/api/modules")
    module_id = list_response.json()["items"][0]["id"]

    response = client.post(
        f"/api/modules/{module_id}/test-run",
        json={
            "test_user": "demo_user_001",
            "date": "2026-06-15",
            "input_payload": {
                "sun_sign": "白羊座",
                "moon_sign": "处女座",
                "nickname": "max",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert data["final_json"]["module_id"] == module_id
    assert data["model_request"]
    assert data["model_raw_response"]

    detail_response = client.get(f"/api/modules/{module_id}")
    detail = detail_response.json()
    assert detail["recent_calls"][0]["id"] == data["id"]
