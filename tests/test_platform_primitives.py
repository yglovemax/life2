import pytest
import types
import json
from pathlib import Path
from datetime import UTC, datetime


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
    assert queue.size() == 0


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


def test_database_runtime_status_parses_postgres_pgvector_plan(monkeypatch):
    from app.core.settings import get_settings
    from app.db import database_runtime_status, reset_db_runtime

    monkeypatch.setenv("NEXA_DATABASE_URL", "postgresql+psycopg://nexa:secret@db.example.com:5432/nexa")
    monkeypatch.setenv("NEXA_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("NEXA_EMBEDDING_DIMENSIONS", "1536")
    get_settings.cache_clear()
    reset_db_runtime()

    try:
        status = database_runtime_status(check_connection=False)
        assert status["database"]["backend"] == "postgresql"
        assert "secret" not in status["database"]["safe_url"]
        assert status["pgvector"]["planned"] is True
        assert status["pgvector"]["extension"] == "vector"
        assert status["pgvector"]["dimensions"] == 1536
        assert status["pgvector"]["target_tables"] == ["knowledge_chunks", "memory_items"]
    finally:
        get_settings.cache_clear()
        reset_db_runtime()


def test_pgvector_migration_declares_vector_columns_and_indexes():
    migration = Path("alembic/versions/20260617_0002_pgvector_embeddings.py")

    assert migration.exists()
    content = migration.read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in content
    assert "knowledge_chunks" in content
    assert "memory_items" in content
    assert "vector(1536)" in content
    assert "ivfflat" in content


def test_openai_embedding_provider_sends_dimensions_and_normalizes_vector(monkeypatch):
    from app.core.settings import get_settings
    from app.services import build_text_embedding_payload

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": [{"embedding": [0.1, 0.2, 0.3]}],
                    "usage": {"prompt_tokens": 8, "total_tokens": 8},
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("app.services.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("NEXA_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("NEXA_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("NEXA_OPENAI_BASE_URL", "https://api.openai.test/v1")
    monkeypatch.setenv("NEXA_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("NEXA_EMBEDDING_DIMENSIONS", "3")
    get_settings.cache_clear()

    try:
        payload = build_text_embedding_payload("月亮代表情绪安全感")
        assert captured["url"] == "https://api.openai.test/v1/embeddings"
        assert captured["headers"]["Authorization"] == "Bearer sk-test"
        assert captured["body"] == {
            "model": "text-embedding-3-small",
            "input": "月亮代表情绪安全感",
            "dimensions": 3,
        }
        assert captured["timeout"] == 45
        assert payload["provider"] == "openai"
        assert payload["model"] == "text-embedding-3-small"
        assert payload["dimensions"] == 3
        assert payload["vector"] == [0.1, 0.2, 0.3]
        assert payload["usage"]["total_tokens"] == 8
    finally:
        get_settings.cache_clear()


def test_openai_embedding_provider_without_key_falls_back_to_mock(monkeypatch):
    from app.core.settings import get_settings
    from app.services import build_text_embedding_payload

    monkeypatch.setenv("NEXA_EMBEDDING_PROVIDER", "openai")
    monkeypatch.delenv("NEXA_OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()

    try:
        payload = build_text_embedding_payload("用户喜欢稳定回应")
        assert payload["provider"] == "mock"
        assert payload["fallback_reason"] == "openai_api_key_missing"
        assert payload["features"]
    finally:
        get_settings.cache_clear()


def test_pgvector_literal_formats_openai_embedding_vector():
    from app.services import embedding_vector_literal

    payload = {"vector": [0.1, -0.25, "3.5"], "dimensions": 3}

    assert embedding_vector_literal(payload) == "[0.1,-0.25,3.5]"
    assert embedding_vector_literal({"features": {"abc": 1.0}}) == ""


def test_sync_pgvector_embedding_updates_postgres_vector_column_only():
    from app.services import sync_pgvector_embedding

    class FakeDialect:
        def __init__(self, name):
            self.name = name

    class FakeBind:
        def __init__(self, name):
            self.dialect = FakeDialect(name)

    class FakeSession:
        def __init__(self, dialect_name):
            self.bind = FakeBind(dialect_name)
            self.calls = []

        def get_bind(self):
            return self.bind

        def execute(self, statement, params):
            self.calls.append((str(statement), params))

    postgres = FakeSession("postgresql")
    sqlite = FakeSession("sqlite")
    payload = {"vector": [0.1, 0.2, 0.3]}

    assert sync_pgvector_embedding(postgres, "knowledge_chunks", 9, payload) is True
    sql, params = postgres.calls[0]
    assert "UPDATE knowledge_chunks SET embedding = CAST(:embedding AS vector)" in sql
    assert params == {"embedding": "[0.1,0.2,0.3]", "id": 9}

    assert sync_pgvector_embedding(sqlite, "knowledge_chunks", 9, payload) is False
    assert sqlite.calls == []


def test_pgvector_knowledge_search_uses_vector_operator_and_preserves_score():
    from app.services import search_knowledge_with_pgvector

    class FakeDialect:
        name = "postgresql"

    class FakeBind:
        dialect = FakeDialect()

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return [{"id": 2, "semantic_score": 0.91}, {"id": 1, "semantic_score": 0.72}]

    class FakeScalars:
        def all(self):
            now = datetime(2026, 6, 21, tzinfo=UTC)
            return [
                types.SimpleNamespace(
                    id=1,
                    source_id=1,
                    title="普通内容",
                    content="普通内容",
                    tags=["八字"],
                    chunk_index=1,
                    embedding_payload={"provider": "openai", "model": "text-embedding-3-small", "hash": "a", "dimensions": 3},
                    embedding_model="text-embedding-3-small",
                    embedding_hash="a",
                    created_at=now,
                ),
                types.SimpleNamespace(
                    id=2,
                    source_id=1,
                    title="甲木事业",
                    content="甲木日主适合主动开局。",
                    tags=["八字", "事业"],
                    chunk_index=2,
                    embedding_payload={"provider": "openai", "model": "text-embedding-3-small", "hash": "b", "dimensions": 3},
                    embedding_model="text-embedding-3-small",
                    embedding_hash="b",
                    created_at=now,
                ),
            ]

    class FakeSession:
        def __init__(self):
            self.executed = []

        def get_bind(self):
            return FakeBind()

        def execute(self, statement, params):
            self.executed.append((str(statement), params))
            return FakeRows()

        def scalars(self, query):
            return FakeScalars()

    session = FakeSession()
    results = search_knowledge_with_pgvector(
        session,
        {"provider": "openai", "model": "text-embedding-3-small", "vector": [0.1, 0.2, 0.3]},
        tags=["事业"],
        limit=1,
    )

    sql, params = session.executed[0]
    assert "embedding <=> CAST(:embedding AS vector)" in sql
    assert params["embedding"] == "[0.1,0.2,0.3]"
    assert results[0]["title"] == "甲木事业"
    assert results[0]["semantic_score"] == 0.91


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


def test_platform_runtime_status_reports_redis_health_and_redacts_url(monkeypatch):
    from app.core.settings import get_settings
    from app.platform.runtime import platform_runtime_status, reset_platform_runtime

    class FakeRedisClient:
        def __init__(self):
            self.lists = {"nexa:tasks": ["task-a", "task-b"]}

        def ping(self):
            return True

        def llen(self, key):
            return len(self.lists.get(key) or [])

    class FakeRedis:
        @staticmethod
        def from_url(url, decode_responses=True):
            return FakeRedisClient()

    monkeypatch.setitem(__import__("sys").modules, "redis", types.SimpleNamespace(Redis=FakeRedis))
    monkeypatch.setenv("NEXA_TASK_QUEUE_BACKEND", "redis")
    monkeypatch.setenv("NEXA_RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setenv("NEXA_REDIS_URL", "redis://:secret-pass@localhost:6379/4")
    get_settings.cache_clear()
    reset_platform_runtime()

    try:
        status = platform_runtime_status()
        assert status["queue"]["backend"] == "redis"
        assert status["queue"]["pending_tasks"] == 2
        assert status["queue"]["shared_across_processes"] is True
        assert status["rate_limit"]["backend"] == "redis"
        assert status["redis"]["configured"] is True
        assert status["redis"]["connected"] is True
        assert "secret-pass" not in status["redis"]["safe_url"]
        assert status["redis"]["safe_url"] == "redis://:***@localhost:6379/4"
    finally:
        get_settings.cache_clear()
        reset_platform_runtime()
