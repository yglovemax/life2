import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def rule_spec() -> dict:
    return {
        "output_template": {
            "day_master": "{{input.day_master}}",
            "score": "{{map.day_master_scores[input.day_master]}}",
            "label": "{{map.labels[input.day_master]}}",
        },
        "maps": {
            "day_master_scores": {"甲木": 82, "乙木": 76},
            "labels": {"甲木": "主动开局", "乙木": "柔韧生长"},
        },
    }


def test_rule_algorithm_can_be_created_tested_published_and_executed():
    slug = f"bazi-day-master-score-{uuid4().hex}"
    created = client.post(
        "/api/algorithms",
        json={
            "slug": slug,
            "name": "日主评分算法",
            "domain": "bazi",
            "algorithm_type": "rule_spec",
            "description": "根据日主映射输出评分和标签。",
            "spec": rule_spec(),
            "input_schema": {"required": ["day_master"]},
            "output_schema": {"required": ["day_master", "score", "label"]},
        },
    )

    assert created.status_code == 200
    algorithm = created.json()
    assert algorithm["slug"] == slug
    assert algorithm["status"] == "draft"
    assert algorithm["versions"][0]["version"] == 1

    test_run = client.post(
        f"/api/algorithms/{algorithm['id']}/test-run",
        json={"input_payload": {"day_master": "甲木"}, "operator": "qa"},
    )

    assert test_run.status_code == 200
    test_data = test_run.json()
    assert test_data["run_mode"] == "test"
    assert test_data["status"] == "ok"
    assert test_data["output_payload"] == {"day_master": "甲木", "score": 82, "label": "主动开局"}

    blocked = client.post(f"/api/algorithms/{algorithm['id']}/execute", json={"input_payload": {"day_master": "乙木"}})
    assert blocked.status_code == 400
    assert "发布" in blocked.json()["detail"]

    published = client.post(f"/api/algorithms/{algorithm['id']}/publish", json={"operator": "max"})

    assert published.status_code == 200
    published_data = published.json()
    assert published_data["status"] == "active"
    assert published_data["active_version"]["status"] == "published"

    executed = client.post(
        f"/api/algorithms/{algorithm['id']}/execute",
        json={"input_payload": {"day_master": "乙木"}, "operator": "app"},
    )

    assert executed.status_code == 200
    execute_data = executed.json()
    assert execute_data["run_mode"] == "execute"
    assert execute_data["status"] == "ok"
    assert execute_data["output_payload"] == {"day_master": "乙木", "score": 76, "label": "柔韧生长"}

    listed = client.get("/api/algorithms")
    assert listed.status_code == 200
    assert any(item["id"] == algorithm["id"] and item["active_version"]["id"] == published_data["active_version"]["id"] for item in listed.json()["items"])


def test_algorithm_upload_creates_draft_rule_algorithm_from_json():
    slug = f"uploaded-bazi-rule-{uuid4().hex}"
    uploaded = client.post(
        "/api/algorithms/uploads",
        json={
            "files": [
                {
                    "filename": "bazi-rule.json",
                    "content": json.dumps(
                        {
                            "slug": slug,
                            "name": "上传日主规则",
                            "domain": "bazi",
                            "spec": rule_spec(),
                            "input_schema": {"required": ["day_master"]},
                            "output_schema": {"required": ["day_master", "score", "label"]},
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        },
    )

    assert uploaded.status_code == 200
    data = uploaded.json()
    assert data["uploaded"] == 1
    assert data["algorithms"][0]["slug"] == slug
    assert data["algorithms"][0]["status"] == "draft"


def test_algorithm_upload_rejects_unsafe_code_payload():
    response = client.post(
        "/api/algorithms/uploads",
        json={
            "files": [
                {
                    "filename": "unsafe.py",
                    "content": "print('do not run arbitrary code')",
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "JSON" in response.json()["detail"]
    assert "不执行" in response.json()["detail"]
