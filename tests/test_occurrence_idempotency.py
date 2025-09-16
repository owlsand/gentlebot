from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import session_scope
from app.models.scheduled_task import ScheduledTask
from app.models.task_occurrence import OccurrenceState, TaskOccurrence
from app.scheduler.enqueue import _upsert_occurrence


def test_occurrence_upsert_is_idempotent(session_factory):
    with session_scope(session_factory) as session:
        ScheduledTask.create(
            session,
            name="idempotent",
            handler="app.handlers.examples.mariners_post_game_summary",
            schedule_kind="CRON",
            schedule_expr="*/5 * * * *",
            timezone="UTC",
            status="active",
        )

    now = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
    later = now + timedelta(minutes=5)

    with session_scope(session_factory) as session:
        task = session.scalars(select(ScheduledTask)).one()
        occurrence_key = TaskOccurrence.compute_occurrence_key(
            task.id, task.schedule_kind, task.schedule_expr, now, task.idempotency_scope
        )
        _upsert_occurrence(
            session,
            task,
            occurrence_key,
            now,
            OccurrenceState.ENQUEUED,
            now,
            now,
        )

    with session_scope(session_factory) as session:
        occurrence = session.scalars(select(TaskOccurrence)).one()
        first_updated = occurrence.updated_at

    with session_scope(session_factory) as session:
        task = session.scalars(select(ScheduledTask)).one()
        occurrence_key = TaskOccurrence.compute_occurrence_key(
            task.id, task.schedule_kind, task.schedule_expr, now, task.idempotency_scope
        )
        _upsert_occurrence(
            session,
            task,
            occurrence_key,
            now,
            OccurrenceState.ENQUEUED,
            now,
            later,
        )

    with session_scope(session_factory) as session:
        occurrence = session.scalars(select(TaskOccurrence)).one()

    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    assert _ensure_utc(occurrence.updated_at) > _ensure_utc(first_updated)
