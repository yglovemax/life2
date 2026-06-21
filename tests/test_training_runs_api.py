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


def test_training_quality_report_flags_blocking_risks_before_publish():
    source = create_source()
    response = client.post(
        "/api/training/runs",
        json={
            "source_id": source["id"],
            "simulate_model_response": [
                {
                    "title": "高风险承诺规则",
                    "body": "客户一定会获得投资收益，也可以用这个方法治疗焦虑。",
                    "domain": "astrology",
                    "tags": ["风险样本"],
                    "rule_type": "unsafe_rule",
                    "use_when": "客户询问投资和健康时",
                    "avoid_when": "无",
                    "examples": [],
                    "confidence": 0.93,
                }
            ],
        },
    )
    assert response.status_code == 200
    run = response.json()

    report_response = client.get(f"/api/training/runs/{run['id']}/quality-report")

    assert report_response.status_code == 200
    report = report_response.json()
    assert report["run_id"] == run["id"]
    assert report["status"] == "blocked"
    assert report["can_publish"] is False
    issue_codes = {issue["code"] for issue in report["issues"]}
    assert {"absolute_claim", "investment_advice", "medical_advice"}.issubset(issue_codes)
    assert report["metrics"]["blocker_count"] >= 3


def test_training_publish_blocks_quality_failures_until_overridden():
    source = create_source()
    response = client.post(
        "/api/training/runs",
        json={
            "source_id": source["id"],
            "simulate_model_response": [
                {
                    "title": "阻断发布规则",
                    "body": "这条内容保证客户稳赚，并且一定会改变命运。",
                    "domain": "astrology",
                    "tags": ["风险样本"],
                    "rule_type": "unsafe_rule",
                    "use_when": "客户问财运时",
                    "avoid_when": "无",
                    "examples": [],
                    "confidence": 0.9,
                }
            ],
        },
    )
    assert response.status_code == 200
    run = response.json()

    blocked = client.post(f"/api/training/runs/{run['id']}/publish", json={"title": "风险发布"})
    assert blocked.status_code == 400
    assert "训练质检未通过" in blocked.json()["detail"]

    override = client.post(
        f"/api/training/runs/{run['id']}/publish",
        json={"title": "风险发布", "override_quality_gate": True, "operator": "qa"},
    )
    assert override.status_code == 200
    published = override.json()
    assert published["status"] == "published"
    assert published["quality_report"]["status"] == "blocked"
    assert published["quality_report"]["override"] is True


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


def test_failed_training_run_can_be_retried_with_new_payload(monkeypatch):
    from app.core.settings import get_settings
    from app.platform.runtime import reset_platform_runtime
    from app.worker import process_next_task

    monkeypatch.setenv("NEXA_TASK_QUEUE_BACKEND", "memory")
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        source = create_source()
        first = client.post(
            "/api/training/runs",
            json={
                "source_id": source["id"],
                "simulate_model_response": "不是合法 JSON",
            },
        )
        assert first.status_code == 200
        failed = first.json()
        assert failed["status"] == "failed"

        retry = client.post(
            f"/api/training/runs/{failed['id']}/retry",
            json={
                "run_mode": "queued",
                "simulate_model_response": json.dumps(
                    {
                        "chunks": [
                            {
                                "title": "月亮重试规则",
                                "body": "失败后重试可以重新生成知识草稿。",
                                "domain": "astrology",
                                "tags": ["月亮", "重试"],
                                "rule_type": "interpretation",
                                "use_when": "训练运行失败后",
                                "avoid_when": "不要保留脏数据",
                                "examples": [],
                                "confidence": 0.79,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            },
        )
        assert retry.status_code == 200
        retried = retry.json()
        assert retried["id"] == failed["id"]
        assert retried["status"] == "queued"
        assert retried["run_mode"] == "queued"
        assert retried["task_id"].startswith("task_")

        assert process_next_task() is True

        detail = client.get(f"/api/training/runs/{failed['id']}")
        assert detail.status_code == 200
        run = detail.json()
        assert run["status"] == "completed"
        assert run["draft_count"] == 1
        assert run["draft_chunks"][0]["title"] == "月亮重试规则"
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()


def test_training_queue_status_reports_pending_runs(monkeypatch):
    from app.core.settings import get_settings
    from app.platform.runtime import reset_platform_runtime

    monkeypatch.setenv("NEXA_TASK_QUEUE_BACKEND", "memory")
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        source = create_source()
        queued = client.post(
            "/api/training/runs",
            json={
                "source_id": source["id"],
                "run_mode": "queued",
                "simulate_model_response": json.dumps(
                    {
                        "chunks": [
                            {
                                "title": "队列状态规则",
                                "body": "查看当前队列积压。",
                                "domain": "astrology",
                                "tags": ["队列"],
                                "rule_type": "interpretation",
                                "use_when": "需要看 worker backlog 时",
                                "avoid_when": "不要忽略排队任务",
                                "examples": [],
                                "confidence": 0.71,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            },
        ).json()

        response = client.get("/api/training/queue-status")
        assert response.status_code == 200
        data = response.json()
        assert data["backend"] == "memory"
        assert data["pending_tasks"] >= 1
        assert data["runs"]["queued"] >= 1
        assert queued["id"] in data["queued_run_ids"]
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()


def test_worker_can_drain_multiple_tasks(monkeypatch):
    from app.core.settings import get_settings
    from app.platform.runtime import reset_platform_runtime
    from app.worker import drain_tasks

    monkeypatch.setenv("NEXA_TASK_QUEUE_BACKEND", "memory")
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        for title in ["A", "B"]:
            source = create_source()
            client.post(
                "/api/training/runs",
                json={
                    "source_id": source["id"],
                    "run_mode": "queued",
                    "simulate_model_response": json.dumps(
                        {
                            "chunks": [
                                {
                                    "title": f"{title} 队列规则",
                                    "body": "批量消费任务。",
                                    "domain": "astrology",
                                    "tags": ["批量"],
                                    "rule_type": "interpretation",
                                    "use_when": "worker 批处理时",
                                    "avoid_when": "不要只跑一个任务就停",
                                    "examples": [],
                                    "confidence": 0.7,
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                },
            )

        assert drain_tasks(limit=2) == 2
        status = client.get("/api/training/queue-status").json()
        assert status["pending_tasks"] == 0
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()


def test_queued_training_run_can_be_canceled_and_worker_skips_it(monkeypatch):
    from app.core.settings import get_settings
    from app.platform.runtime import reset_platform_runtime
    from app.worker import process_next_task

    monkeypatch.setenv("NEXA_TASK_QUEUE_BACKEND", "memory")
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        source = create_source()
        queued = client.post(
            "/api/training/runs",
            json={
                "source_id": source["id"],
                "run_mode": "queued",
                "simulate_model_response": json.dumps(
                    {
                        "chunks": [
                            {
                                "title": "取消规则",
                                "body": "如果取消则不再执行。",
                                "domain": "astrology",
                                "tags": ["取消"],
                                "rule_type": "interpretation",
                                "use_when": "任务取消时",
                                "avoid_when": "不要继续执行",
                                "examples": [],
                                "confidence": 0.7,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            },
        ).json()

        canceled = client.post(f"/api/training/runs/{queued['id']}/cancel", json={})
        assert canceled.status_code == 200
        canceled_run = canceled.json()
        assert canceled_run["status"] == "canceled"

        assert process_next_task() is True

        detail = client.get(f"/api/training/runs/{queued['id']}").json()
        assert detail["status"] == "canceled"
        assert detail["draft_count"] == 0
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()
