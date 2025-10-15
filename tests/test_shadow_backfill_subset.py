from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.db import session_scope
from app.models.scheduled_task import ScheduledTask
from app.models.task_occurrence import OccurrenceState, TaskOccurrence
from app.scheduler.enqueue import enqueue_due_occurrences_for_tasks


def test_enqueue_for_tasks_limits_to_shadow_subset(session_factory):
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    with session_scope(session_factory) as session:
        shadow_task = ScheduledTask.create(
            session,
            name="shadow-only",
            handler="app.handlers.examples.mariners_post_game_summary",
            schedule_kind="CRON",
            schedule_expr="* * * * *",
            timezone="UTC",
            status="shadow",
            is_active=True,
        )
        active_task = ScheduledTask.create(
            session,
            name="active-task",
            handler="app.handlers.examples.mariners_post_game_summary",
            schedule_kind="CRON",
            schedule_expr="* * * * *",
            timezone="UTC",
            status="active",
            is_active=True,
        )

    with session_scope(session_factory) as session:
        shadow = session.get(ScheduledTask, shadow_task.id)
        active = session.get(ScheduledTask, active_task.id)
        created = enqueue_due_occurrences_for_tasks(session, [shadow], now=now)
        assert created == 0
        shadow_id = shadow.id
        active_id = active.id

    with session_scope(session_factory) as session:
        shadow_occurrences = session.scalars(
            select(TaskOccurrence).where(TaskOccurrence.task_id == shadow_id)
        ).all()
        active_occurrence_count = session.scalar(
            select(func.count())
            .select_from(TaskOccurrence)
            .where(TaskOccurrence.task_id == active_id)
        )

    assert shadow_occurrences
    assert all(occ.state == OccurrenceState.SCHEDULED for occ in shadow_occurrences)
    assert active_occurrence_count == 0
