"""Enqueue scheduled task occurrences."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models.scheduled_task import ScheduledTask
from app.models.task_occurrence import OccurrenceState, TaskOccurrence
from app.scheduler.cron import compute_due_times, compute_next_run_after


log = logging.getLogger("gentlebot.scheduler.enqueue")

LOOKAHEAD_SECONDS = 60
MAX_ENQUEUED_PER_TASK = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)




def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _build_insert(session: Session):
    table = TaskOccurrence.__table__
    if session.bind.dialect.name == "postgresql":
        return pg_insert(table)
    if session.bind.dialect.name == "sqlite":
        return sqlite_insert(table)
    return table.insert()


def _upsert_occurrence(
    session: Session,
    task: ScheduledTask,
    occurrence_key: str,
    scheduled_for: datetime,
    initial_state: str,
    enqueued_at: Optional[datetime],
    now: datetime,
) -> int:
    insert_stmt = _build_insert(session).values(
        task_id=task.id,
        occurrence_key=occurrence_key,
        scheduled_for=scheduled_for,
        state=initial_state,
        enqueued_at=enqueued_at,
        created_at=now,
        updated_at=now,
    )
    if hasattr(insert_stmt, "on_conflict_do_update"):
        insert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[TaskOccurrence.__table__.c.task_id, TaskOccurrence.__table__.c.occurrence_key],
            set_={"updated_at": now},
        )
    if hasattr(insert_stmt, "returning"):
        insert_stmt = insert_stmt.returning(TaskOccurrence.__table__.c.id)
    result = session.execute(insert_stmt)
    occurrence_id: Optional[int] = None
    if hasattr(result, "scalar_one_or_none"):
        occurrence_id = result.scalar_one_or_none()
    if occurrence_id is None:
        occurrence_id = session.scalar(
            select(TaskOccurrence.id).where(
                TaskOccurrence.task_id == task.id, TaskOccurrence.occurrence_key == occurrence_key
            )
        )
    return int(occurrence_id)


def enqueue_due_occurrences(session: Session, now: Optional[datetime] = None) -> int:
    """Upsert occurrences for all active tasks within the lookahead window."""

    now = now or _now()
    window_end = now + timedelta(seconds=LOOKAHEAD_SECONDS)

    tasks = session.scalars(
        select(ScheduledTask).where(
            ScheduledTask.is_active.is_(True), ScheduledTask.status.in_(["active", "shadow"])
        )
    ).all()

    enqueued = 0
    for task in tasks:
        due_times: List[datetime]
        try:
            due_times = compute_due_times(
                task.schedule_kind, task.schedule_expr, task.timezone, now, window_end
            )
        except Exception as exc:  # pragma: no cover - schedule validation
            log.exception("failed computing schedule", extra={"task_id": task.id, "error": str(exc)})
            continue

        if not due_times:
            try:
                next_run = compute_next_run_after(
                    task.schedule_kind, task.schedule_expr, task.timezone, window_end
                )
            except Exception:  # pragma: no cover
                next_run = None
            task.touch_next_run(next_run)
            continue

        queued_count = session.scalar(
            select(func.count()).select_from(TaskOccurrence).where(
                TaskOccurrence.task_id == task.id,
                TaskOccurrence.state == OccurrenceState.ENQUEUED,
            )
        )
        if queued_count and queued_count >= MAX_ENQUEUED_PER_TASK:
            log.warning(
                "backpressure: refusing to enqueue more occurrences", extra={"task_id": task.id}
            )
            continue

        for scheduled_for in due_times:
            occurrence_key = TaskOccurrence.compute_occurrence_key(
                task.id, task.schedule_kind, task.schedule_expr, scheduled_for, task.idempotency_scope
            )
            initial_state = (
                OccurrenceState.ENQUEUED if task.status == "active" else OccurrenceState.SCHEDULED
            )
            enqueued_at = now if initial_state == OccurrenceState.ENQUEUED else None
            occurrence_id = _upsert_occurrence(
                session,
                task,
                occurrence_key,
                scheduled_for,
                initial_state,
                enqueued_at,
                now,
            )
            occurrence = session.get(TaskOccurrence, occurrence_id)
            if occurrence is None:
                continue
            if task.status == "active":
                if occurrence.state in (OccurrenceState.SCHEDULED, OccurrenceState.FAILED):
                    occurrence.mark_enqueued(now)
                    occurrence.reason = None
                    enqueued += 1
                elif occurrence.state == OccurrenceState.ENQUEUED:
                    created_recently = abs((_as_utc(occurrence.created_at) - now).total_seconds()) < 1
                    if occurrence.enqueued_at is None or _as_utc(occurrence.enqueued_at) <= now:
                        occurrence.enqueued_at = now
                        occurrence.updated_at = now
                    if created_recently:
                        enqueued += 1
        try:
            next_run = compute_next_run_after(
                task.schedule_kind, task.schedule_expr, task.timezone, window_end
            )
        except Exception:  # pragma: no cover
            next_run = None
        task.touch_next_run(next_run)
    return enqueued


def enqueue_cycle(now: Optional[datetime] = None) -> int:
    """High-level helper used by scripts to perform a single enqueue cycle."""

    with session_scope() as session:
        return enqueue_due_occurrences(session, now=now)


__all__ = ["enqueue_cycle", "enqueue_due_occurrences", "LOOKAHEAD_SECONDS"]
