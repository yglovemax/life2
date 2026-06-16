import pytest


def test_local_object_storage_writes_bytes_and_blocks_path_escape(tmp_path):
    from app.platform.object_storage import LocalObjectStorage, safe_object_key

    storage = LocalObjectStorage(tmp_path)
    stored = storage.put_bytes(safe_object_key("knowledge/uploads", "moon.md"), b"moon", "text/markdown")

    assert stored.key == "knowledge/uploads/moon.md"
    assert stored.size_bytes == 4
    assert storage.read_bytes(stored.key) == b"moon"

    with pytest.raises(ValueError):
        storage.put_bytes("../outside.txt", b"escape", "text/plain")


def test_in_memory_task_queue_processes_envelopes_once():
    from app.platform.tasks import InMemoryTaskQueue, TaskEnvelope, run_task_once

    queue = InMemoryTaskQueue()
    queue.enqueue(TaskEnvelope(task_type="knowledge.ingest", payload={"source_id": "src_1"}))
    queue.enqueue(TaskEnvelope(task_type="memory.summarize", payload={"user_id": "u_1"}))

    handled = []
    assert run_task_once(queue, lambda task: handled.append(task.task_type)) is True
    assert run_task_once(queue, lambda task: handled.append(task.task_type)) is True
    assert run_task_once(queue, lambda task: handled.append(task.task_type)) is False
    assert handled == ["knowledge.ingest", "memory.summarize"]


def test_in_memory_rate_limiter_blocks_after_limit():
    from app.platform.rate_limit import InMemoryRateLimiter

    limiter = InMemoryRateLimiter()

    assert limiter.allow("user:1", limit=2, window_seconds=60, now=1000) is True
    assert limiter.allow("user:1", limit=2, window_seconds=60, now=1001) is True
    assert limiter.allow("user:1", limit=2, window_seconds=60, now=1002) is False
    assert limiter.allow("user:1", limit=2, window_seconds=60, now=1061) is True


def test_object_storage_factory_uses_configured_upload_dir(monkeypatch, tmp_path):
    from app.core.settings import get_settings
    from app.platform.runtime import get_object_storage, reset_platform_runtime

    monkeypatch.setenv("NEXA_OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("NEXA_UPLOAD_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        storage = get_object_storage()
        stored = storage.put_bytes("knowledge/uploads/factory.txt", b"factory", "text/plain")
        assert stored.key == "knowledge/uploads/factory.txt"
        assert (tmp_path / "knowledge" / "uploads" / "factory.txt").read_bytes() == b"factory"
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()


def test_worker_once_returns_zero_when_queue_is_empty(monkeypatch):
    from app.core.settings import get_settings
    from app.platform.runtime import reset_platform_runtime
    from app.worker import main

    monkeypatch.setenv("NEXA_TASK_QUEUE_BACKEND", "memory")
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        assert main(["once"]) == 0
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()
