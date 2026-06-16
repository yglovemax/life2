from __future__ import annotations

import sys
import time

from app.db import get_session_factory
from app.platform.runtime import get_task_queue
from app.platform.tasks import run_task_once
from app.services import execute_memory_summary_job, execute_training_run_job


def task_handlers() -> dict:
    return {
        "memory.summarize": handle_memory_summary_task,
        "training.run": handle_training_run_task,
    }


def handle_training_run_task(payload: dict) -> None:
    session = get_session_factory()()
    try:
        execute_training_run_job(session, int(payload.get("run_id") or 0))
    finally:
        session.close()


def handle_memory_summary_task(payload: dict) -> None:
    session = get_session_factory()()
    try:
        item_ids = [int(item_id) for item_id in (payload.get("memory_item_ids") or []) if str(item_id).strip()]
        execute_memory_summary_job(session, int(payload.get("user_id") or 0), memory_item_ids=item_ids)
    finally:
        session.close()


def process_next_task() -> bool:
    return run_task_once(get_task_queue(), task_handlers())


def drain_tasks(limit: int = 10) -> int:
    handled = 0
    for _ in range(max(limit, 0)):
        if not process_next_task():
            break
        handled += 1
    return handled


def run_forever(poll_interval_seconds: float = 1.0) -> None:
    while True:
        handled = process_next_task()
        if not handled:
            time.sleep(max(poll_interval_seconds, 0.1))


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if argv and argv[0] == "once":
        limit = int(argv[1]) if len(argv) > 1 else 1
        drain_tasks(limit=limit)
        return 0
    run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
