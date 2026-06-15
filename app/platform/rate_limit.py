from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    reset_at: float
    current: int


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self.buckets: dict[str, list[float]] = {}

    def allow(self, key: str, limit: int, window_seconds: int, now: float | None = None) -> bool:
        return self.check(key, limit, window_seconds, now=now).allowed

    def check(self, key: str, limit: int, window_seconds: int, now: float | None = None) -> RateLimitDecision:
        current_time = time.time() if now is None else now
        cutoff = current_time - window_seconds
        hits = [hit for hit in self.buckets.get(key, []) if hit > cutoff]
        allowed = len(hits) < limit
        if allowed:
            hits.append(current_time)
        self.buckets[key] = hits
        reset_at = (hits[0] + window_seconds) if hits else current_time + window_seconds
        return RateLimitDecision(
            allowed=allowed,
            remaining=max(limit - len(hits), 0),
            reset_at=reset_at,
            current=len(hits),
        )


class RedisRateLimiter:
    def __init__(self, client: object, prefix: str = "nexa:rate") -> None:
        self.client = client
        self.prefix = prefix

    def allow(self, key: str, limit: int, window_seconds: int, now: float | None = None) -> bool:
        return self.check(key, limit, window_seconds, now=now).allowed

    def check(self, key: str, limit: int, window_seconds: int, now: float | None = None) -> RateLimitDecision:
        redis_key = f"{self.prefix}:{key}"
        current = int(self.client.incr(redis_key))
        if current == 1:
            self.client.expire(redis_key, window_seconds)
        ttl = int(self.client.ttl(redis_key))
        current_time = time.time() if now is None else now
        allowed = current <= limit
        return RateLimitDecision(
            allowed=allowed,
            remaining=max(limit - current, 0) if allowed else 0,
            reset_at=current_time + max(ttl, 0),
            current=current,
        )
