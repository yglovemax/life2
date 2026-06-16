import pytest
import types


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


def test_db_runtime_can_switch_database_url_after_reset(monkeypatch, tmp_path):
    from app.core.settings import get_settings
    from app.db import get_engine, reset_db_runtime

    first_db = tmp_path / "first.db"
    second_db = tmp_path / "second.db"

    monkeypatch.setenv("NEXA_DATABASE_URL", f"sqlite:///{first_db}")
    get_settings.cache_clear()
    reset_db_runtime()
    first_engine = get_engine()

    monkeypatch.setenv("NEXA_DATABASE_URL", f"sqlite:///{second_db}")
    get_settings.cache_clear()
    reset_db_runtime()
    second_engine = get_engine()

    try:
        assert str(first_engine.url).endswith(str(first_db))
        assert str(second_engine.url).endswith(str(second_db))
        assert str(first_engine.url) != str(second_engine.url)
    finally:
        get_settings.cache_clear()
        reset_db_runtime()


def test_runtime_builds_redis_task_queue_and_rate_limiter(monkeypatch):
    from app.core.settings import get_settings
    from app.platform.runtime import get_rate_limiter, get_task_queue, reset_platform_runtime
    from app.platform.tasks import RedisTaskQueue
    from app.platform.rate_limit import RedisRateLimiter

    calls = []

    class FakeRedisClient:
        pass

    class FakeRedis:
        @staticmethod
        def from_url(url, decode_responses=True):
            calls.append((url, decode_responses))
            return FakeRedisClient()

    monkeypatch.setitem(__import__("sys").modules, "redis", types.SimpleNamespace(Redis=FakeRedis))
    monkeypatch.setenv("NEXA_TASK_QUEUE_BACKEND", "redis")
    monkeypatch.setenv("NEXA_RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setenv("NEXA_REDIS_URL", "redis://localhost:6379/2")
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        queue = get_task_queue()
        limiter = get_rate_limiter()
        assert isinstance(queue, RedisTaskQueue)
        assert isinstance(limiter, RedisRateLimiter)
        assert queue.client is limiter.client
        assert calls == [("redis://localhost:6379/2", True)]
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()


def test_redis_queue_and_rate_limiter_share_backend_state(monkeypatch):
    from app.core.settings import get_settings
    from app.platform.runtime import get_redis_client, reset_platform_runtime
    from app.platform.tasks import RedisTaskQueue, TaskEnvelope, run_task_once

    class FakeRedisClient:
        def __init__(self):
            self.lists = {}
            self.counters = {}
            self.expirations = {}

        def rpush(self, key, value):
            self.lists.setdefault(key, []).append(value)

        def lpop(self, key):
            items = self.lists.get(key) or []
            if not items:
                return None
            return items.pop(0)

        def incr(self, key):
            self.counters[key] = int(self.counters.get(key, 0)) + 1
            return self.counters[key]

        def expire(self, key, ttl):
            self.expirations[key] = ttl

        def ttl(self, key):
            return self.expirations.get(key, -1)

    client = FakeRedisClient()

    class FakeRedis:
        @staticmethod
        def from_url(url, decode_responses=True):
            return client

    monkeypatch.setitem(__import__("sys").modules, "redis", types.SimpleNamespace(Redis=FakeRedis))
    monkeypatch.setenv("NEXA_REDIS_URL", "redis://localhost:6379/3")
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        shared_client = get_redis_client()
        queue_a = RedisTaskQueue(shared_client)
        queue_b = RedisTaskQueue(shared_client)
        queue_a.enqueue(TaskEnvelope(task_type="training.run", payload={"run_id": 9}))
        handled = []
        assert run_task_once(queue_b, lambda task: handled.append(task.payload["run_id"])) is True
        assert handled == [9]

        from app.platform.rate_limit import RedisRateLimiter

        redis_limiter = RedisRateLimiter(shared_client)
        first = redis_limiter.check("user:9", limit=1, window_seconds=60, now=1000)
        second = redis_limiter.check("user:9", limit=1, window_seconds=60, now=1001)
        assert first.allowed is True
        assert second.allowed is False
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()
