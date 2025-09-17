from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db import session_scope
from app.models.scheduled_task import ScheduledTask
from app.models.task_execution import TaskExecution
from app.models.task_occurrence import OccurrenceState, TaskOccurrence
from app.worker import runner


def test_concurrency_limit_honored(monkeypatch, session_factory):
    base_time = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
    times = [
        base_time,
        base_time + timedelta(seconds=1),
        base_time + timedelta(seconds=2),
        base_time + timedelta(seconds=3),
        base_time + timedelta(seconds=4),
    ]

    def fake_now():
        return times.pop(0)

    monkeypatch.setattr(runner, "_now", fake_now)

    with session_scope(session_factory) as session:
        task = ScheduledTask.create(
            session,
            name="no-overlap",
            handler="ignored",
            schedule_kind="CRON",
            schedule_expr="*/5 * * * *",
            timezone="UTC",
            status="active",
            concurrency_limit=1,
        )
        session.flush()
        for idx in range(2):
            scheduled = base_time + timedelta(minutes=idx)
            occurrence = TaskOccurrence(
                task_id=task.id,
                occurrence_key=TaskOccurrence.compute_occurrence_key(
                    task.id, task.schedule_kind, task.schedule_expr, scheduled, task.idempotency_scope
                ),
                scheduled_for=scheduled,
                state=OccurrenceState.ENQUEUED,
                enqueued_at=base_time,
            )
            session.add(occurrence)

    execution_order = []

    def handler_stub(ctx, payload):
        execution_order.append(ctx["occurrence_id"])
        return {"ok": True}

    processed = runner.run_worker_cycle(
        "worker-1",
        session_factory=session_factory,
        resolver=lambda _name: handler_stub,
        now=base_time,
    )
    assert processed == 2

    with session_scope(session_factory) as session:
        executions = session.scalars(select(TaskExecution).order_by(TaskExecution.attempt_no)).all()
        assert len(executions) == 2
        assert execution_order == [exec.occurrence_id for exec in executions]
        assert executions[0].finished_at <= executions[1].started_at
        assert session.scalar(
            select(func.count()).select_from(TaskOccurrence).where(TaskOccurrence.state == OccurrenceState.RUNNING)
        ) == 0
