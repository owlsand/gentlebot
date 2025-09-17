#!/usr/bin/env python3
"""Backfill occurrences in shadow mode without executing handlers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import get_engine, session_scope, create_session_factory
from app.models.scheduled_task import ScheduledTask
from app.scheduler.enqueue import enqueue_due_occurrences


def backfill(now: datetime | None = None) -> int:
    engine = get_engine()
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        shadow_tasks = session.scalars(
            select(ScheduledTask).where(ScheduledTask.status == "shadow")
        ).all()
        if not shadow_tasks:
            print("No shadow tasks configured")
            return 0
        return enqueue_due_occurrences(session, now=now)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill shadow occurrences")
    parser.add_argument(
        "--now",
        type=str,
        help="ISO8601 timestamp to use instead of current time",
    )
    args = parser.parse_args()
    timestamp = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    created = backfill(timestamp)
    print(f"Created {created} occurrences in shadow mode")


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
