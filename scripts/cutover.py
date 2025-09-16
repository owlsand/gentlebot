#!/usr/bin/env python3
"""Activate scheduled tasks by toggling their status in the ledger."""
from __future__ import annotations

import argparse
from typing import Iterable

from sqlalchemy import select

from app.db import get_engine, session_scope, create_session_factory
from app.models.scheduled_task import ScheduledTask


def activate_tasks(names: Iterable[str]) -> int:
    engine = get_engine()
    session_factory = create_session_factory(engine)
    name_list = list(names)
    with session_scope(session_factory) as session:
        tasks = session.scalars(select(ScheduledTask).where(ScheduledTask.name.in_(name_list))).all()
        if not tasks:
            print("No matching tasks found")
            return 0
        for task in tasks:
            task.activate()
        print(f"Activated {len(tasks)} tasks")
        return len(tasks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Activate scheduler tasks")
    parser.add_argument("names", nargs="+", help="Task names to activate")
    args = parser.parse_args()
    activate_tasks(args.names)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
