from fastapi.testclient import TestClient
from uuid import uuid4

from app.main import app


client = TestClient(app)


def admin_headers() -> dict:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_health_reports_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_admin_login_returns_session_and_me_endpoint_resolves_user():
    login_response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert login_response.status_code == 200
    login = login_response.json()
    assert login["token"].startswith("adm_")
    assert login["user"]["username"] == "admin"
    assert login["user"]["role"] == "owner"

    me_response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {login['token']}"})
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "admin"


def test_admin_login_rejects_wrong_password_and_records_audit():
    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert response.status_code == 401

    events = client.get("/api/security/audit-events?event_type=admin_login_failed", headers=admin_headers()).json()["items"]
    assert events
    assert events[0]["event_type"] == "admin_login_failed"
    assert events[0]["severity"] == "warning"


def test_seeded_module_center_contains_phase_one_pages():
    response = client.get("/api/modules")
    assert response.status_code == 200
    data = response.json()

    page_names = {item["page_name"] for item in data["items"]}
    module_names = {item["name"] for item in data["items"]}

    assert "出生星盘解读页" in page_names
    assert "每日星座运势页" in page_names
    assert "八字命盘解读页" in page_names
    assert "八字每日运势页" in page_names
    assert "星盘详解" in module_names
    assert "每日寄语" in module_names
    assert "日主与格局" in module_names
    assert "今日行动建议" in module_names


def test_bazi_knowledge_hits_can_rank_by_day_master_query():
    create_older = client.post(
        "/api/knowledge-sources",
        json={
            "title": "乙木事业规则",
            "source_type": "markdown",
            "content": "# 乙木\n乙木日主在事业推进上更适合先稳住节奏，再决定是否加码。",
            "tags": ["八字", "事业"],
        },
    )
    create_newer = client.post(
        "/api/knowledge-sources",
        json={
            "title": "甲木事业规则",
            "source_type": "markdown",
            "content": "# 甲木\n甲木日主在事业推进上更适合先拉高目标，再逐步拆解执行。",
            "tags": ["八字", "事业"],
        },
    )
    assert create_older.status_code == 200
    assert create_newer.status_code == 200

    pages_response = client.get("/api/pages")
    models_response = client.get("/api/models")
    page_id = pages_response.json()["items"][0]["id"]
    model_id = models_response.json()["items"][0]["id"]
    slug = f"bazi-knowledge-test-{uuid4().hex}"

    module_response = client.post(
        "/api/modules",
        json={
            "page_id": page_id,
            "model_id": model_id,
            "slug": slug,
            "name": "八字知识命中测试模块",
            "owner": "算法",
            "status": "draft",
            "fallback_content": "备用内容",
            "algorithm_fields": {"required": ["day_master"]},
            "knowledge_tags": ["八字", "事业"],
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
    assert module_response.status_code == 200
    module_id = module_response.json()["id"]

    trace_response = client.post(
        f"/api/modules/{module_id}/test-run",
        json={
            "test_user": "demo_user_001",
            "date": "2026-06-17",
            "input_payload": {"day_master": "乙木"},
        },
    )
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["knowledge_hits"]
    assert trace["knowledge_hits"][0]["title"] == "乙木"
    assert "乙木日主" in trace["knowledge_hits"][0]["content"]


def test_knowledge_taxonomy_exposes_bazi_dimensions():
    response = client.get("/api/knowledge/taxonomy")
    assert response.status_code == 200
    data = response.json()
    systems = {item["system"] for item in data["items"]}
    assert "astrology" in systems
    assert "bazi" in systems
    bazi = next(item for item in data["items"] if item["system"] == "bazi")
    assert "日主" in bazi["dimensions"]
    assert "十神" in bazi["dimensions"]


def test_bazi_seeded_modules_have_domain_specific_contracts_and_prompt():
    modules = client.get("/api/modules").json()["items"]
    bazi_module = next(item for item in modules if item["slug"] == "bazi-day-master-pattern")

    detail = client.get(f"/api/modules/{bazi_module['id']}").json()
    field_names = {field["field_name"] for field in detail["fields"]}

    assert {"day_master", "pattern_summary", "strength_hint", "action_advice"}.issubset(field_names)
    assert detail["algorithm_fields"]["required"] == ["user_profile", "birth_profile", "bazi_facts"]
    assert "四柱" in detail["prompt"]["algorithm_data_template"]
    assert "八字" in detail["prompt"]["module_rules"]


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


def test_test_run_accepts_valid_model_json_and_records_raw_response():
    module_id = client.get("/api/modules").json()["items"][0]["id"]
    simulated_response = '{"title":"今日提醒","summary":"适合把计划拆小，并保留弹性。"}'

    response = client.post(
        f"/api/modules/{module_id}/test-run",
        json={
            "test_user": "demo_user_001",
            "date": "2026-06-15",
            "simulate_model_response": simulated_response,
            "input_payload": {"sun_sign": "白羊座", "nickname": "max"},
        },
    )

    assert response.status_code == 200
    trace = response.json()
    assert trace["status"] == "ok"
    assert trace["fallback_triggered"] is False
    assert trace["fallback_reason"] == ""
    assert trace["model_raw_response"] == simulated_response
    assert trace["final_json"]["title"] == "今日提醒"
    assert trace["final_json"]["summary"] == "适合把计划拆小，并保留弹性。"
    assert trace["final_json"]["module_id"] == module_id
    assert trace["final_json"]["module_slug"]


def test_test_run_invalid_model_json_triggers_fallback_and_keeps_raw_response():
    module = client.get("/api/modules").json()["items"][0]
    detail = client.get(f"/api/modules/{module['id']}").json()

    response = client.post(
        f"/api/modules/{module['id']}/test-run",
        json={
            "test_user": "demo_user_001",
            "date": "2026-06-15",
            "simulate_model_response": "不是 JSON",
            "input_payload": {"sun_sign": "白羊座", "nickname": "max"},
        },
    )

    assert response.status_code == 200
    trace = response.json()
    assert trace["status"] == "fallback"
    assert trace["fallback_triggered"] is True
    assert trace["fallback_reason"] == "invalid_json"
    assert trace["model_raw_response"] == "不是 JSON"
    assert detail["fallback_content"] in trace["final_json"]["summary"]
    assert trace["final_json"]["fallback_reason"] == "invalid_json"


def test_test_run_missing_required_model_field_triggers_fallback():
    module = client.get("/api/modules").json()["items"][0]

    response = client.post(
        f"/api/modules/{module['id']}/test-run",
        json={
            "test_user": "demo_user_001",
            "date": "2026-06-15",
            "simulate_model_response": '{"title":"缺字段样本"}',
            "input_payload": {"sun_sign": "白羊座", "nickname": "max"},
        },
    )

    assert response.status_code == 200
    trace = response.json()
    assert trace["status"] == "fallback"
    assert trace["fallback_triggered"] is True
    assert trace["fallback_reason"] == "missing_required_fields"
    assert trace["final_json"]["missing_fields"] == ["summary"]


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


def test_issue_can_be_created_for_module_and_updates_open_issue_count():
    module = client.get("/api/modules").json()["items"][0]

    response = client.post(
        f"/api/modules/{module['id']}/issues",
        json={
            "title": "字段 summary 内容太空",
            "issue_type": "content_quality",
            "owner": "Prompt",
            "notes": "测试样本里缺少具体建议。",
        },
    )

    assert response.status_code == 200
    issue = response.json()
    assert issue["module_id"] == module["id"]
    assert issue["title"] == "字段 summary 内容太空"
    assert issue["status"] == "open"
    assert issue["owner"] == "Prompt"

    detail = client.get(f"/api/modules/{module['id']}").json()
    assert any(item["id"] == issue["id"] for item in detail["issues"])

    rows = client.get("/api/modules").json()["items"]
    updated_module = next(item for item in rows if item["id"] == module["id"])
    assert updated_module["open_issues"] >= 1


def test_issue_can_be_listed_filtered_and_resolved():
    module = client.get("/api/modules").json()["items"][0]
    created = client.post(
        f"/api/modules/{module['id']}/issues",
        json={
            "title": "Fallback 文案需要调整",
            "issue_type": "fallback",
            "owner": "QA",
            "notes": "备用内容太泛。",
        },
    ).json()

    open_list = client.get("/api/issues?status=open&owner=QA").json()["items"]
    assert any(item["id"] == created["id"] for item in open_list)

    response = client.put(
        f"/api/issues/{created['id']}",
        json={
            "status": "resolved",
            "owner": "Prompt",
            "notes": "已补充具体建议并通过测试。",
        },
    )

    assert response.status_code == 200
    resolved = response.json()
    assert resolved["status"] == "resolved"
    assert resolved["owner"] == "Prompt"
    assert resolved["notes"] == "已补充具体建议并通过测试。"

    resolved_list = client.get("/api/issues?status=resolved").json()["items"]
    assert any(item["id"] == created["id"] for item in resolved_list)


def test_model_provider_key_is_created_once_and_list_is_redacted():
    api_key = f"sk-test-router-secret-{uuid4().hex}"
    response = client.post(
        "/api/model-provider-keys",
        headers=admin_headers(),
        json={
            "name": "OpenAI Production",
            "provider": "openai",
            "api_key": api_key,
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["api_key"] == api_key
    assert created["key"]["name"] == "OpenAI Production"
    assert created["key"]["status"] == "active"
    assert created["key"]["token_prefix"].startswith("sk-t")

    list_response = client.get("/api/model-provider-keys", headers=admin_headers())
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert any(item["id"] == created["key"]["id"] for item in items)
    assert api_key not in str(items)
    assert all("token_hash" not in item for item in items)


def test_output_policy_routes_to_primary_model_and_exposes_orchestration_preview():
    models = client.get("/api/models").json()["items"]
    primary = models[0]
    fallback = models[-1]

    create_response = client.post(
        "/api/output-policies",
        headers=admin_headers(),
        json={
            "name": "深度解读高质量",
            "quality_tier": "premium",
            "primary_model_id": primary["id"],
            "fallback_model_id": fallback["id"],
            "max_output_tokens": 680,
            "temperature_x100": 65,
            "response_format": "json",
            "safety_rules": "避免医疗、法律、投资承诺。",
            "is_default": True,
        },
    )

    assert create_response.status_code == 200
    policy = create_response.json()
    assert policy["name"] == "深度解读高质量"
    assert policy["max_output_tokens"] == 680
    assert policy["primary_model"]["id"] == primary["id"]
    assert policy["fallback_model"]["id"] == fallback["id"]

    preview_response = client.post(
        "/api/model-router/preview",
        json={
            "module_id": client.get("/api/modules").json()["items"][0]["id"],
            "policy_id": policy["id"],
            "input_payload": {"topic": "relationship", "risk_level": "normal"},
        },
    )

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["selected_model"]["id"] == primary["id"]
    assert preview["fallback_model"]["id"] == fallback["id"]
    assert preview["policy"]["id"] == policy["id"]
    assert preview["orchestration"]["max_output_tokens"] == 680
    assert preview["orchestration"]["temperature_x100"] == 65
    assert preview["orchestration"]["response_format"] == "json"
    assert "避免医疗" in preview["orchestration"]["safety_rules"]


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


def test_invalid_app_token_is_written_to_security_audit_log():
    response = client.post(
        "/api/app/modules/birth-basic-chart-info/render",
        headers={"Authorization": "Bearer wrong-token"},
        json={"input_payload": {"sun_sign": "白羊座"}},
    )

    assert response.status_code == 401
    events = client.get("/api/security/audit-events?event_type=app_auth_failed", headers=admin_headers()).json()["items"]
    assert events
    assert events[0]["event_type"] == "app_auth_failed"
    assert events[0]["severity"] == "warning"
    assert "wrong-token" not in str(events[0])


def test_app_key_can_be_created_used_once_returned_and_listed_without_secret():
    module = client.get("/api/modules").json()["items"][0]
    client.post(f"/api/modules/{module['id']}/publish", json={"status": "live", "operator": "qa"})

    create_response = client.post(
        "/api/security/app-keys",
        headers=admin_headers(),
        json={"name": "iOS App Production", "scopes": ["app:render"]},
    )
    assert create_response.status_code == 200
    created = create_response.json()
    token = created["token"]
    assert token.startswith("nexa_")
    assert created["key"]["name"] == "iOS App Production"
    assert created["key"]["status"] == "active"

    keys = client.get("/api/security/app-keys", headers=admin_headers()).json()["items"]
    assert any(item["id"] == created["key"]["id"] for item in keys)
    assert token not in str(keys)
    assert all("token_hash" not in item for item in keys)

    app_response = client.post(
        f"/api/app/modules/{module['slug']}/render",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_id": "app_user_001", "input_payload": {"sun_sign": "白羊座"}},
    )
    assert app_response.status_code == 200
    assert app_response.json()["meta"]["request_type"] == "official"


def test_revoked_app_key_cannot_call_app_api_and_security_status_counts_it():
    module = client.get("/api/modules").json()["items"][0]
    client.post(f"/api/modules/{module['id']}/publish", json={"status": "live", "operator": "qa"})
    created = client.post("/api/security/app-keys", headers=admin_headers(), json={"name": "Temporary Partner Key"}).json()
    token = created["token"]

    revoke_response = client.post(f"/api/security/app-keys/{created['key']['id']}/revoke", headers=admin_headers(), json={"operator": "admin"})
    assert revoke_response.status_code == 200
    assert revoke_response.json()["status"] == "revoked"

    app_response = client.post(
        f"/api/app/modules/{module['slug']}/render",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_id": "app_user_001", "input_payload": {"sun_sign": "白羊座"}},
    )
    assert app_response.status_code == 401

    status = client.get("/api/security/status").json()
    assert status["app_keys"]["revoked"] >= 1
    assert status["audit_events"]["total"] >= 1
    assert status["token_policy"]["using_default_dev_token"] is True


def test_security_app_key_management_requires_admin_session():
    response = client.post("/api/security/app-keys", json={"name": "No Session Key"})
    assert response.status_code == 401

    audit_response = client.get("/api/security/audit-events")
    assert audit_response.status_code == 401
