from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_text() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class TaskEnvelope:
    task_type: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:20]}")
    user_id: str = ""
    tenant_id: str = "default"
    created_at: str = field(default_factory=utc_text)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, value: str | bytes) -> "TaskEnvelope":
        text = value.decode("utf-8") if isinstance(value, bytes) else value
        return cls(**json.loads(text))


class InMemoryTaskQueue:
    def __init__(self) -> None:
        self.items: list[TaskEnvelope] = []

    def enqueue(self, task: TaskEnvelope) -> str:
        self.items.append(task)
        return task.id

    def push(self, task: TaskEnvelope) -> str:
        return self.enqueue(task)

    def pop(self) -> TaskEnvelope | None:
        if not self.items:
            return None
        return self.items.pop(0)


class RedisTaskQueue:
    def __init__(self, client: object, key: str = "nexa:tasks") -> None:
        self.client = client
        self.key = key

    def enqueue(self, task: TaskEnvelope) -> str:
        self.client.rpush(self.key, task.to_json())
        return task.id

    def push(self, task: TaskEnvelope) -> str:
        return self.enqueue(task)

    def pop(self) -> TaskEnvelope | None:
        raw = self.client.lpop(self.key)
        return TaskEnvelope.from_json(raw) if raw else None


def run_task_once(
    queue: InMemoryTaskQueue | RedisTaskQueue,
    handler: Callable[[TaskEnvelope], Any] | dict[str, Callable[[dict[str, Any]], Any]],
) -> bool:
    task = queue.pop()
    if task is None:
        return False
    if isinstance(handler, dict):
        task_handler = handler.get(task.task_type)
        if task_handler is None:
            raise ValueError(f"No handler registered for task type: {task.task_type}")
        task_handler(task.payload)
    else:
        handler(task)
    return True
