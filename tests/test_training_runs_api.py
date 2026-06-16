import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def create_source() -> dict:
    suffix = uuid4().hex[:8]
    response = client.post(
        "/api/knowledge-sources",
        json={
            "title": f"训练源 {suffix}",
            "source_type": "markdown",
            "content": "# 月亮\n月亮代表情绪安全感，解读时要避免绝对化。",
            "tags": ["占星", "训练测试"],
        },
    )
    assert response.status_code == 200
    return response.json()


def test_training_run_creates_draft_chunks_from_model_json():
    source = create_source()
    simulated_response = {
        "chunks": [
            {
                "title": "月亮情绪安全感",
                "body": "月亮相关内容适合用于解释用户的情绪需求和安全感来源。",
                "domain": "astrology",
                "tags": ["月亮", "情绪"],
                "rule_type": "interpretation",
                "use_when": "用户询问情绪、亲密关系和安全感时",
                "avoid_when": "不要断言对方一定会怎样",
                "examples": ["可以说：你更需要被稳定回应。"],
                "confidence": 0.88,
            }
        ]
    }

    response = client.post(
        "/api/training/runs",
        json={
            "source_id": source["id"],
            "simulate_model_response": json.dumps(simulated_response, ensure_ascii=False),
            "tags": ["训练测试"],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["draft_count"] == 1
    assert data["source_id"] == source["id"]
    assert data["draft_chunks"][0]["title"] == "月亮情绪安全感"
    assert "ai_training" in data["draft_chunks"][0]["tags"]
    assert "边界：" in data["draft_chunks"][0]["content"]


def test_training_run_publish_creates_searchable_knowledge_source():
    source = create_source()
    response = client.post(
        "/api/training/runs",
        json={
            "source_id": source["id"],
            "simulate_model_response": [
                {
                    "title": "月亮咨询规则",
                    "body": "月亮知识应优先用于情绪安全感解释。",
                    "domain": "astrology",
                    "tags": ["月亮", "情绪安全感"],
                    "rule_type": "consulting_rule",
                    "use_when": "客户问到关系中的安定感",
                    "avoid_when": "不要替客户做重大决定",
                    "examples": [],
                    "confidence": 0.91,
                }
            ],
        },
    )
    assert response.status_code == 200
    run = response.json()

    publish_response = client.post(f"/api/training/runs/{run['id']}/publish", json={"title": "AI 训练发布：月亮"})

    assert publish_response.status_code == 200
    published = publish_response.json()
    assert published["status"] == "published"
    assert published["published_source"]["title"] == "AI 训练发布：月亮"
    assert published["published_source"]["source_type"] == "ai_training"
    assert published["published_source"]["chunk_count"] >= 1

    search_response = client.post(
        "/api/knowledge/search",
        json={"query": "情绪安全感", "tags": ["ai_training"], "limit": 5},
    )
    assert search_response.status_code == 200
    assert any("月亮" in item["title"] for item in search_response.json()["items"])


def test_training_run_records_failed_invalid_json():
    source = create_source()
    response = client.post(
        "/api/training/runs",
        json={
            "source_id": source["id"],
            "simulate_model_response": "这不是 JSON",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert "模型输出不是有效 JSON" in data["error"]
    assert data["draft_count"] == 0


def test_training_run_can_be_queued_and_processed_by_worker(monkeypatch):
    from app.core.settings import get_settings
    from app.platform.runtime import reset_platform_runtime
    from app.worker import process_next_task

    monkeypatch.setenv("NEXA_TASK_QUEUE_BACKEND", "memory")
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        source = create_source()
        response = client.post(
            "/api/training/runs",
            json={
                "source_id": source["id"],
                "run_mode": "queued",
                "simulate_model_response": json.dumps(
                    {
                        "chunks": [
                            {
                                "title": "月亮队列规则",
                                "body": "月亮内容需要通过队列训练再入库。",
                                "domain": "astrology",
                                "tags": ["月亮", "队列"],
                                "rule_type": "interpretation",
                                "use_when": "用户问到情绪安全感时",
                                "avoid_when": "不要做绝对判断",
                                "examples": [],
                                "confidence": 0.83,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            },
        )

        assert response.status_code == 200
        queued = response.json()
        assert queued["status"] == "queued"
        assert queued["run_mode"] == "queued"
        assert queued["task_id"].startswith("task_")
        assert queued["draft_count"] == 0

        assert process_next_task() is True

        detail = client.get(f"/api/training/runs/{queued['id']}")
        assert detail.status_code == 200
        run = detail.json()
        assert run["status"] == "completed"
        assert run["run_mode"] == "queued"
        assert run["draft_count"] == 1
        assert run["draft_chunks"][0]["title"] == "月亮队列规则"
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()
