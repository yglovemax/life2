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


def test_markdown_knowledge_source_upload_chunks_and_searches_by_tag():
    response = client.post(
        "/api/knowledge-sources",
        json={
            "title": "白羊座知识库",
            "source_type": "markdown",
            "content": "# 白羊座\n白羊座强调行动力和开端。\n\n## 咨询表达\n适合给出直接、清晰的行动建议。",
            "tags": ["占星", "白羊座"],
        },
    )
    assert response.status_code == 200
    source = response.json()
    assert source["title"] == "白羊座知识库"
    assert source["chunk_count"] >= 2

    search_response = client.post(
        "/api/knowledge/search",
        json={"query": "行动力", "tags": ["白羊座"], "limit": 5},
    )
    assert search_response.status_code == 200
    results = search_response.json()["items"]
    assert results
    assert any("行动力" in item["content"] for item in results)


def test_manual_knowledge_entry_can_be_created_and_listed():
    response = client.post(
        "/api/knowledge-entries",
        json={
            "title": "日运表达规则",
            "content": "日运输出需要有行动建议，并避免绝对化承诺。",
            "tags": ["日运", "表达规则"],
        },
    )
    assert response.status_code == 200
    entry = response.json()
    assert entry["title"] == "日运表达规则"
    assert entry["tags"] == ["日运", "表达规则"]

    list_response = client.get("/api/knowledge-chunks?tag=日运")
    assert list_response.status_code == 200
    assert any(item["title"] == "日运表达规则" for item in list_response.json()["items"])


def test_module_test_records_knowledge_hits_for_matching_tags():
    client.post(
        "/api/knowledge-sources",
        json={
            "title": "占星通用安全规则",
            "source_type": "markdown",
            "content": "# 安全边界\n占星解读必须避免医疗、法律和投资承诺。",
            "tags": ["占星", "安全边界"],
        },
    )
    module_id = client.get("/api/modules").json()["items"][0]["id"]
    trace = client.post(
        f"/api/modules/{module_id}/test-run",
        json={
            "test_user": "demo_user_001",
            "date": "2026-06-15",
            "input_payload": {"sun_sign": "白羊座"},
        },
    ).json()

    assert trace["knowledge_hits"]
    assert trace["knowledge_hits"][0]["title"]
    assert "安全边界" in trace["knowledge_hits"][0]["tags"] or "占星" in trace["knowledge_hits"][0]["tags"]


def test_cost_summary_groups_calls_by_page_module_and_model():
    module = client.get("/api/modules").json()["items"][0]
    trace = client.post(
        f"/api/modules/{module['id']}/test-run",
        json={
            "test_user": "demo_user_001",
            "date": "2026-06-15",
            "input_payload": {"sun_sign": "白羊座", "nickname": "max"},
        },
    ).json()

    response = client.get("/api/costs/summary")
    assert response.status_code == 200
    data = response.json()

    assert data["total_cost_cents"] >= trace["estimated_cost_cents"]
    assert data["total_calls"] >= 1
    assert any(item["page_name"] == module["page_name"] for item in data["by_page"])
    assert any(item["module_id"] == module["id"] and item["cost_cents"] >= trace["estimated_cost_cents"] for item in data["by_module"])
    assert any(item["model_name"] == trace["model_name"] for item in data["by_model"])


def test_forced_fallback_test_run_uses_module_fallback_and_creates_alert():
    module = client.get("/api/modules").json()["items"][0]
    detail = client.get(f"/api/modules/{module['id']}").json()

    response = client.post(
        f"/api/modules/{module['id']}/test-run",
        json={
            "test_user": "demo_user_001",
            "date": "2026-06-15",
            "force_fallback": True,
            "fallback_reason": "model_timeout",
            "input_payload": {"sun_sign": "白羊座"},
        },
    )

    assert response.status_code == 200
    trace = response.json()
    assert trace["status"] == "fallback"
    assert trace["fallback_triggered"] is True
    assert trace["fallback_reason"] == "model_timeout"
    assert trace["final_json"]["fallback"] is True
    assert detail["fallback_content"] in trace["final_json"]["summary"]

    alerts = client.get("/api/fallback-alerts").json()["items"]
    assert any(item["trace_id"] == trace["id"] and item["reason"] == "model_timeout" for item in alerts)


def test_publish_and_rollback_create_module_versions_and_update_status():
    module_id = client.get("/api/modules").json()["items"][0]["id"]
    before = client.get(f"/api/modules/{module_id}").json()

    publish_response = client.post(
        f"/api/modules/{module_id}/publish",
        json={"status": "gray", "operator": "qa", "notes": "进入灰度验证"},
    )
    assert publish_response.status_code == 200
    published = publish_response.json()
    assert published["status"] == "gray"
    assert published["version"] == before["version"] + 1
    assert published["versions"][0]["status"] == "gray"
    assert published["versions"][0]["snapshot"]["notes"] == "进入灰度验证"

    rollback_response = client.post(
        f"/api/modules/{module_id}/rollback",
        json={"operator": "qa", "reason": "灰度结果不稳定"},
    )
    assert rollback_response.status_code == 200
    rolled_back = rollback_response.json()
    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["version"] == published["version"] + 1

    versions_response = client.get(f"/api/modules/{module_id}/versions")
    assert versions_response.status_code == 200
    versions = versions_response.json()["items"]
    assert versions[0]["status"] == "rolled_back"
    assert any(item["status"] == "gray" for item in versions)


def test_app_module_api_requires_token():
    response = client.post(
        "/api/app/modules/birth-basic-chart-info/render",
        json={"input_payload": {"sun_sign": "白羊座"}},
    )

    assert response.status_code == 401


def test_app_module_api_returns_json_with_request_trace_id_and_official_trace():
    module = client.get("/api/modules").json()["items"][0]
    client.post(f"/api/modules/{module['id']}/publish", json={"status": "live", "operator": "qa"})

    response = client.post(
        f"/api/app/modules/{module['slug']}/render",
        headers={"Authorization": "Bearer dev-app-token"},
        json={
            "user_id": "app_user_001",
            "date": "2026-06-15",
            "input_payload": {"sun_sign": "白羊座", "nickname": "max"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["request_id"].startswith("req_")
    assert data["trace_id"]
    assert data["module"]["slug"] == module["slug"]
    assert data["result"]["module_slug"] == module["slug"]
    assert data["meta"]["request_type"] == "official"

    traces = client.get("/api/call-traces?request_type=official").json()["items"]
    assert any(trace["id"] == data["trace_id"] and trace["request_type"] == "official" for trace in traces)


def test_app_page_api_renders_live_or_gray_modules_only():
    modules = client.get("/api/modules").json()["items"]
    birth_modules = [item for item in modules if item["page_name"] == "出生星盘解读页"]
    live_module = birth_modules[0]
    draft_module = birth_modules[1]
    client.post(f"/api/modules/{live_module['id']}/publish", json={"status": "gray", "operator": "qa"})

    response = client.post(
        "/api/app/pages/birth-chart-reading/render",
        headers={"X-Nexa-Api-Key": "dev-app-token"},
        json={
            "user_id": "app_user_001",
            "date": "2026-06-15",
            "input_payload": {"sun_sign": "白羊座", "nickname": "max"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    slugs = [item["module"]["slug"] for item in data["modules"]]
    assert data["request_id"].startswith("req_")
    assert data["page"]["slug"] == "birth-chart-reading"
    assert live_module["slug"] in slugs
    assert draft_module["slug"] not in slugs
    assert all(item["trace_id"] for item in data["modules"])
