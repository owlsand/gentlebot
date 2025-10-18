from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.handlers.examples import mariners_post_game_summary
from app.models.scheduled_task import ScheduledTask
from app.models.task_execution import TaskExecution
from app.models.task_occurrence import OccurrenceState, TaskOccurrence
from app.worker.runner import CLAIM_LEASE_TIMEOUT, run_worker_cycle


@pytest.fixture(autouse=True)
def reset_handler_state():
    mariners_post_game_summary._POSTED_MARKERS.clear()
    mariners_post_game_summary._ATTEMPTS.clear()
    yield
    mariners_post_game_summary._POSTED_MARKERS.clear()
    mariners_post_game_summary._ATTEMPTS.clear()


def test_retry_then_success(monkeypatch, session_factory):
    now = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
    with session_scope(session_factory) as session:
        task = ScheduledTask.create(
            session,
            name="retry",
            handler="app.handlers.examples.mariners_post_game_summary",
            schedule_kind="CRON",
            schedule_expr="*/5 * * * *",
            timezone="UTC",
            status="active",
            payload={"team": "SEA", "game_id": "123", "fail_once": True},
        )
        session.flush()
        occurrence = TaskOccurrence(
            task_id=task.id,
            occurrence_key=TaskOccurrence.compute_occurrence_key(
                task.id, task.schedule_kind, task.schedule_expr, now, task.idempotency_scope
            ),
            scheduled_for=now,
            state=OccurrenceState.ENQUEUED,
            enqueued_at=now,
        )
        session.add(occurrence)

    monkeypatch.setattr("app.worker.runner.random.uniform", lambda *_args, **_kwargs: 0.0)

    processed = run_worker_cycle("worker-1", session_factory=session_factory, now=now)
    assert processed == 1

    with session_scope(session_factory) as session:
        occurrence = session.scalars(select(TaskOccurrence)).one()
        assert occurrence.state == OccurrenceState.ENQUEUED
        assert occurrence.enqueued_at is not None
        enqueued_at = occurrence.enqueued_at
        if enqueued_at.tzinfo is None:
            enqueued_at = enqueued_at.replace(tzinfo=timezone.utc)
        assert enqueued_at > now
        executions = session.scalars(select(TaskExecution).order_by(TaskExecution.attempt_no)).all()
        assert len(executions) == 1
        assert executions[0].status == "failed"
        next_attempt_time = occurrence.enqueued_at
        if next_attempt_time.tzinfo is None:
            next_attempt_time = next_attempt_time.replace(tzinfo=timezone.utc)

    processed = run_worker_cycle(
        "worker-1",
        session_factory=session_factory,
        now=next_attempt_time + timedelta(seconds=1),
    )
    assert processed == 1

    with session_scope(session_factory) as session:
        occurrence = session.scalars(select(TaskOccurrence)).one()
        assert occurrence.state == OccurrenceState.EXECUTED
        executions = session.scalars(select(TaskExecution).order_by(TaskExecution.attempt_no)).all()
        assert [exec.status for exec in executions] == ["failed", "succeeded"]


def test_releases_stale_running_occurrences(session_factory):
    now = datetime(2024, 3, 1, 18, 0, tzinfo=timezone.utc)
    stale_locked_at = now - CLAIM_LEASE_TIMEOUT - timedelta(seconds=1)

    scheduled_for = now - timedelta(minutes=5)

    with session_scope(session_factory) as session:
        task = ScheduledTask.create(
            session,
            name="stale-claim",
            handler="app.handlers.examples.mariners_post_game_summary",
            schedule_kind="CRON",
            schedule_expr="*/5 * * * *",
            timezone="UTC",
            status="active",
            payload={"team": "SEA", "game_id": "999"},
        )
        session.flush()
        occurrence = TaskOccurrence(
            task_id=task.id,
            occurrence_key=TaskOccurrence.compute_occurrence_key(
                task.id, task.schedule_kind, task.schedule_expr, scheduled_for, task.idempotency_scope
            ),
            scheduled_for=scheduled_for,
            enqueued_at=scheduled_for,
            state=OccurrenceState.RUNNING,
            locked_by="worker-crash",
            locked_at=stale_locked_at,
        )
        session.add(occurrence)

    processed = run_worker_cycle("worker-2", session_factory=session_factory, now=now)
    assert processed == 1

    with session_scope(session_factory) as session:
        occurrence = session.scalars(select(TaskOccurrence)).one()
        assert occurrence.state == OccurrenceState.EXECUTED
        assert occurrence.locked_by is None
        assert occurrence.locked_at is None
        executions = session.scalars(select(TaskExecution)).all()
        assert len(executions) == 1
        assert executions[0].status == "succeeded"
