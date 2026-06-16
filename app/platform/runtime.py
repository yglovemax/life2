from __future__ import annotations

from functools import lru_cache

from app.core.settings import get_settings
from app.platform.object_storage import LocalObjectStorage, ObjectStorage
from app.platform.rate_limit import InMemoryRateLimiter, RedisRateLimiter
from app.platform.tasks import InMemoryTaskQueue, RedisTaskQueue


def build_redis_client() -> object:
    settings = get_settings()
    if not settings.redis_url:
        raise ValueError("NEXA_REDIS_URL is required for redis backends")
    try:
        from redis import Redis
    except ImportError as exc:  # pragma: no cover
        raise ValueError("redis backend requires the `redis` package") from exc
    return Redis.from_url(settings.redis_url, decode_responses=True)


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
        return RedisTaskQueue(build_redis_client())
    raise ValueError(f"unsupported task queue backend: {backend}")


@lru_cache
def get_rate_limiter() -> InMemoryRateLimiter | RedisRateLimiter:
    settings = get_settings()
    backend = settings.rate_limit_backend.strip().lower() or "memory"
    if backend == "memory":
        return InMemoryRateLimiter()
    if backend == "redis":
        return RedisRateLimiter(build_redis_client())
    raise ValueError(f"unsupported rate limiter backend: {backend}")


def reset_platform_runtime() -> None:
    get_object_storage.cache_clear()
    get_task_queue.cache_clear()
    get_rate_limiter.cache_clear()
