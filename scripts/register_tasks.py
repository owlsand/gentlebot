#!/usr/bin/env python3
"""Register existing Gentlebot tasks into the scheduler ledger."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import List, TypedDict

from sqlalchemy import select

from app.db import get_engine, session_scope, create_session_factory
from app.models.scheduled_task import ScheduledTask
from app.scheduler.cron import compute_next_run_after


class TaskDefinition(TypedDict, total=False):
    name: str
    handler: str
    schedule_kind: str
    schedule_expr: str
    timezone: str
    payload: dict
    status: str


TASK_DEFINITIONS: List[TaskDefinition] = [
    {
        "name": "Mariners post-game summary",
        "handler": "app.handlers.examples.mariners_post_game_summary",
        "schedule_kind": "CRON",
        "schedule_expr": "*/2 * * * *",
        "timezone": "America/Los_Angeles",
        "payload": {"league": "MLB", "team": "SEA", "game_id": "demo", "fail_once": False},
        "status": "shadow",
    },
    {
        "name": "Daily Discord haiku",
        "handler": "app.handlers.examples.mariners_post_game_summary",
        "schedule_kind": "CRON",
        "schedule_expr": "0 22 * * *",
        "timezone": "America/Los_Angeles",
        "payload": {},
        "status": "shadow",
    },
    {
        "name": "Fantasy weekly digest",
        "handler": "app.handlers.examples.mariners_post_game_summary",
        "schedule_kind": "CRON",
        "schedule_expr": "0 9 * * MON",
        "timezone": "America/Los_Angeles",
        "payload": {"league": "Yahoo"},
        "status": "shadow",
    },
]


def register_tasks(overwrite: bool = False) -> None:
    engine = get_engine()
    session_factory = create_session_factory(engine)
    now = datetime.now(timezone.utc)
    with session_scope(session_factory) as session:
        for definition in TASK_DEFINITIONS:
            name = definition["name"]
            task = session.scalar(select(ScheduledTask).where(ScheduledTask.name == name))
            if task and not overwrite:
                print(f"Task {name} already exists; skipping")
                continue
            if not task:
                task = ScheduledTask.create(
                    session,
                    name=name,
                    handler=definition["handler"],
                    schedule_kind=definition["schedule_kind"],
                    schedule_expr=definition["schedule_expr"],
                    timezone=definition.get("timezone", "UTC"),
                    payload=definition.get("payload", {}),
                    status=definition.get("status", "shadow"),
                )
            else:
                task.handler = definition["handler"]
                task.schedule_kind = definition["schedule_kind"]
                task.schedule_expr = definition["schedule_expr"]
                task.timezone = definition.get("timezone", "UTC")
                task.payload = definition.get("payload", {})
                task.status = definition.get("status", task.status)
            try:
                next_run = compute_next_run_after(
                    task.schedule_kind, task.schedule_expr, task.timezone, now
                )
            except Exception:
                next_run = None
            task.touch_next_run(next_run)
            print(f"Registered task {name} (next run: {task.next_run_at})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Register Gentlebot tasks")
    parser.add_argument("--overwrite", action="store_true", help="Update existing task definitions")
    args = parser.parse_args()
    register_tasks(overwrite=args.overwrite)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
