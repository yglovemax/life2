from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
APP_HEADERS = {"X-Nexa-Api-Key": "dev-app-token"}


def create_source() -> dict:
    suffix = uuid4().hex[:8]
    response = client.post(
        "/api/knowledge-sources",
        json={
            "title": f"批量重建资料 {suffix}",
            "source_type": "markdown",
            "content": "# 日主\n甲木日主重视生发、方向感和持续成长。",
            "tags": ["八字", "embedding重建"],
        },
    )
    assert response.status_code == 200
    return response.json()


def create_user_with_memory() -> tuple[dict, dict]:
    suffix = uuid4().hex[:8]
    user_response = client.post(
        "/api/app/users",
        headers=APP_HEADERS,
        json={"external_id": f"rebuild-user-{suffix}", "nickname": "重建测试用户"},
    )
    assert user_response.status_code == 200
    user = user_response.json()

    memory_response = client.post(
        f"/api/app/users/{user['id']}/memories",
        headers=APP_HEADERS,
        json={
            "memory_type": "preference",
            "content": "用户希望八字解读先给结论，再给行动建议。",
            "tags": ["八字", "偏好"],
            "importance": 4,
        },
    )
    assert memory_response.status_code == 200
    return user, memory_response.json()


def source_chunks(source_id: int) -> list[dict]:
    response = client.get(f"/api/knowledge-chunks?source_id={source_id}")
    assert response.status_code == 200
    return response.json()["items"]


def user_memories(user_id: int) -> list[dict]:
    response = client.get(f"/api/app/users/{user_id}/memories", headers=APP_HEADERS)
    assert response.status_code == 200
    return response.json()["items"]


def test_embedding_rebuild_sync_refreshes_selected_knowledge_and_memory(monkeypatch):
    from app.core.settings import get_settings

    source = create_source()
    user, memory = create_user_with_memory()
    before_chunk = source_chunks(source["id"])[0]
    before_memory = memory
    next_model = f"mock-rebuild-sync-{uuid4().hex[:8]}"

    monkeypatch.setenv("NEXA_EMBEDDING_MODEL", next_model)
    get_settings.cache_clear()

    try:
        response = client.post(
            "/api/embeddings/rebuild",
            json={
                "target": "all",
                "run_mode": "sync",
                "source_id": source["id"],
                "user_id": user["id"],
                "force": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["run_mode"] == "sync"
        assert data["target"] == "all"
        assert data["processed"] == 2
        assert data["knowledge_chunks"] == 1
        assert data["memory_items"] == 1
        assert data["embedding_model"] == next_model

        after_chunk = source_chunks(source["id"])[0]
        after_memory = user_memories(user["id"])[0]
        assert after_chunk["embedding"]["model"] == next_model
        assert after_chunk["embedding"]["hash"] != before_chunk["embedding"]["hash"]
        assert after_memory["embedding"]["model"] == next_model
        assert after_memory["embedding"]["hash"] != before_memory["embedding"]["hash"]
    finally:
        get_settings.cache_clear()


def test_embedding_rebuild_can_be_queued_and_processed_by_worker(monkeypatch):
    from app.core.settings import get_settings
    from app.platform.runtime import reset_platform_runtime
    from app.worker import process_next_task

    first_model = f"mock-rebuild-before-{uuid4().hex[:8]}"
    next_model = f"mock-rebuild-queued-{uuid4().hex[:8]}"
    monkeypatch.setenv("NEXA_TASK_QUEUE_BACKEND", "memory")
    monkeypatch.setenv("NEXA_EMBEDDING_MODEL", first_model)
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        source = create_source()
        before_chunk = source_chunks(source["id"])[0]
        assert before_chunk["embedding"]["model"] == first_model

        monkeypatch.setenv("NEXA_EMBEDDING_MODEL", next_model)
        get_settings.cache_clear()
        response = client.post(
            "/api/embeddings/rebuild",
            json={
                "target": "knowledge",
                "run_mode": "queued",
                "source_id": source["id"],
                "force": True,
            },
        )
        assert response.status_code == 200
        queued = response.json()
        assert queued["status"] == "queued"
        assert queued["run_mode"] == "queued"
        assert queued["task_id"].startswith("task_")
        assert queued["knowledge_chunks"] == 0
        assert queued["memory_items"] == 0

        assert process_next_task() is True
        after_chunk = source_chunks(source["id"])[0]
        assert after_chunk["embedding"]["model"] == next_model
        assert after_chunk["embedding"]["hash"] != before_chunk["embedding"]["hash"]
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()
