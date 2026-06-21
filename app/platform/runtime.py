from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from app.core.settings import get_settings
from app.platform.object_storage import LocalObjectStorage, ObjectStorage
from app.platform.rate_limit import InMemoryRateLimiter, RedisRateLimiter
from app.platform.tasks import InMemoryTaskQueue, RedisTaskQueue


@lru_cache
def get_redis_client() -> object:
    settings = get_settings()
    if not settings.redis_url:
        raise ValueError("NEXA_REDIS_URL is required for redis backends")
    try:
        from redis import Redis
    except ImportError as exc:  # pragma: no cover
        raise ValueError("redis backend requires the `redis` package") from exc
    return Redis.from_url(settings.redis_url, decode_responses=True)


def build_redis_client() -> object:
    return get_redis_client()


def safe_service_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    netloc = parsed.netloc
    if "@" in netloc:
        credentials, host = netloc.rsplit("@", 1)
        username = credentials.split(":", 1)[0]
        masked = f"{username}:***" if username else ":***"
        netloc = f"{masked}@{host}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def platform_runtime_status(check_connection: bool = True) -> dict:
    settings = get_settings()
    queue_backend = settings.task_queue_backend.strip().lower() or "memory"
    rate_limit_backend = settings.rate_limit_backend.strip().lower() or "memory"
    uses_redis = queue_backend == "redis" or rate_limit_backend == "redis"
    status = {
        "queue": {
            "backend": queue_backend,
            "pending_tasks": None,
            "shared_across_processes": queue_backend == "redis",
            "error": "",
        },
        "rate_limit": {
            "backend": rate_limit_backend,
            "shared_across_processes": rate_limit_backend == "redis",
            "error": "",
        },
        "redis": {
            "configured": bool(settings.redis_url),
            "safe_url": safe_service_url(settings.redis_url),
            "connected": None,
            "error": "",
        },
    }
    if not check_connection:
        return status

    try:
        if uses_redis:
            get_redis_client().ping()
            status["redis"]["connected"] = True
        if queue_backend in {"memory", "redis"}:
            status["queue"]["pending_tasks"] = get_task_queue().size()
    except Exception as exc:  # pragma: no cover - environment-specific diagnostics
        if uses_redis:
            status["redis"]["connected"] = False
            status["redis"]["error"] = str(exc)[:300]
        status["queue"]["error"] = str(exc)[:300]
    return status


@lru_cache
def get_object_storage() -> ObjectStorage:
    settings = get_settings()
    backend = settings.object_storage_backend.strip().lower() or "local"
    if backend == "local":
        return LocalObjectStorage(settings.upload_storage_dir)
    raise ValueError(f"unsupported object storage backend: {backend}")


@lru_cache
def get_task_queue() -> InMemoryTaskQueue | RedisTaskQueue:
    settings = get_settings()
    backend = settings.task_queue_backend.strip().lower() or "memory"
    if backend == "memory":
        return InMemoryTaskQueue()
    if backend == "redis":
        return RedisTaskQueue(get_redis_client())
    raise ValueError(f"unsupported task queue backend: {backend}")


@lru_cache
def get_rate_limiter() -> InMemoryRateLimiter | RedisRateLimiter:
    settings = get_settings()
    backend = settings.rate_limit_backend.strip().lower() or "memory"
    if backend == "memory":
        return InMemoryRateLimiter()
    if backend == "redis":
        return RedisRateLimiter(get_redis_client())
    raise ValueError(f"unsupported rate limiter backend: {backend}")


def reset_platform_runtime() -> None:
    get_redis_client.cache_clear()
    get_object_storage.cache_clear()
    get_task_queue.cache_clear()
    get_rate_limiter.cache_clear()
