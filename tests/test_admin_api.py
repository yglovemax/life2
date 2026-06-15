from fastapi.testclient import TestClient
from uuid import uuid4

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


def test_create_module_saves_prompt_fields_and_fallback_as_draft():
    pages_response = client.get("/api/pages")
    models_response = client.get("/api/models")
    assert pages_response.status_code == 200
    assert models_response.status_code == 200
    page_id = pages_response.json()["items"][0]["id"]
    model_id = models_response.json()["items"][0]["id"]
    slug = f"config-test-{uuid4().hex}"

    response = client.post(
        "/api/modules",
        json={
            "page_id": page_id,
            "model_id": model_id,
            "slug": slug,
            "name": "配置闭环测试模块",
            "owner": "产品经理",
            "status": "draft",
            "fallback_content": "备用内容",
            "algorithm_fields": {"required": ["sun_sign"]},
            "knowledge_tags": ["占星", "测试"],
            "prompt": {
                "shared_prefix": "共享规则",
                "module_rules": "模块规则",
                "algorithm_data_template": "算法模板",
                "user_preferences_template": "偏好模板",
                "final_request_template": "最终请求",
            },
            "fields": [
                {
                    "field_name": "summary",
                    "purpose": "核心内容",
                    "display_position": "测试卡片",
                    "example": "这是一段示例",
                    "source": "ai",
                    "is_ai_generated": True,
                    "is_required": True,
                    "owner": "Prompt",
                    "status": "draft",
                    "change_log": "初始创建",
                }
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["slug"] == slug
    assert data["status"] == "draft"
    assert data["fallback_content"] == "备用内容"
    assert data["prompt"]["module_rules"] == "模块规则"
    assert data["fields"][0]["field_name"] == "summary"


def test_update_module_replaces_prompt_fields_and_keeps_detail_consistent():
    pages_response = client.get("/api/pages")
    models_response = client.get("/api/models")
    page_id = pages_response.json()["items"][0]["id"]
    model_id = models_response.json()["items"][0]["id"]
    slug = f"editable-test-{uuid4().hex}"
    create_response = client.post(
        "/api/modules",
        json={
            "page_id": page_id,
            "model_id": model_id,
            "slug": slug,
            "name": "待编辑模块",
            "owner": "未分配",
            "fallback_content": "旧备用",
            "prompt": {
                "shared_prefix": "旧共享",
                "module_rules": "旧规则",
                "algorithm_data_template": "旧算法",
                "user_preferences_template": "旧偏好",
                "final_request_template": "旧最终",
            },
            "fields": [{"field_name": "old", "purpose": "旧字段", "example": "旧示例"}],
        },
    )
    module_id = create_response.json()["id"]

    update_response = client.put(
        f"/api/modules/{module_id}",
        json={
            "page_id": page_id,
            "model_id": model_id,
            "slug": slug,
            "name": "已编辑模块",
            "owner": "Prompt 负责人",
            "status": "pending_test",
            "fallback_content": "新备用",
            "algorithm_fields": {"required": ["moon_sign", "date"]},
            "knowledge_tags": ["日运", "关系"],
            "prompt": {
                "shared_prefix": "新共享",
                "module_rules": "新规则",
                "algorithm_data_template": "新算法",
                "user_preferences_template": "新偏好",
                "final_request_template": "新最终",
            },
            "fields": [
                {"field_name": "title", "purpose": "标题", "example": "今日建议", "source": "fixed_config", "is_ai_generated": False},
                {"field_name": "summary", "purpose": "正文", "example": "适合沟通", "source": "ai", "is_ai_generated": True},
            ],
        },
    )

    assert update_response.status_code == 200
    data = update_response.json()
    assert data["name"] == "已编辑模块"
    assert data["owner"] == "Prompt 负责人"
    assert data["status"] == "pending_test"
    assert data["fallback_content"] == "新备用"
    assert data["prompt"]["shared_prefix"] == "新共享"
    assert [field["field_name"] for field in data["fields"]] == ["title", "summary"]


def test_test_center_exposes_demo_users():
    response = client.get("/api/test-users")
    assert response.status_code == 200
    data = response.json()

    assert data["items"][0]["id"] == "demo_user_001"
    assert "birth_profile" in data["items"][0]
    assert "preferences" in data["items"][0]


def test_batch_test_run_creates_trace_for_each_selected_module_with_model_override():
    modules_response = client.get("/api/modules")
    models_response = client.get("/api/models")
    module_ids = [item["id"] for item in modules_response.json()["items"][:2]]
    model_id = models_response.json()["items"][-1]["id"]
    model_name = models_response.json()["items"][-1]["display_name"]

    response = client.post(
        "/api/test-runs/batch",
        json={
            "module_ids": module_ids,
            "test_user": "demo_user_001",
            "date": "2026-06-15",
            "model_id": model_id,
            "input_payload": {"sun_sign": "白羊座", "nickname": "max"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert [item["module_id"] for item in data["items"]] == module_ids
    assert all(item["status"] == "ok" for item in data["items"])
    assert all(item["model_name"] == model_name for item in data["items"])


def test_call_trace_can_be_scored_and_keeps_review_notes():
    module_id = client.get("/api/modules").json()["items"][0]["id"]
    trace = client.post(
        f"/api/modules/{module_id}/test-run",
        json={
            "test_user": "demo_user_001",
            "date": "2026-06-15",
            "input_payload": {"sun_sign": "白羊座"},
        },
    ).json()

    response = client.put(
        f"/api/call-traces/{trace['id']}/score",
        json={"manual_score": 4, "reviewer_notes": "语气可用，字段完整。"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["manual_score"] == 4
    assert data["reviewer_notes"] == "语气可用，字段完整。"
