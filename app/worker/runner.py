"""Worker loop that claims occurrences and executes handlers."""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.db import SessionLocal, session_scope
from app.handlers.interface import FatalError, HandlerProtocol, RetryableError, resolve_handler
from app.models.scheduled_task import ScheduledTask
from app.models.task_execution import TaskExecution
from app.models.task_occurrence import ClaimedOccurrence, OccurrenceState, TaskOccurrence


log = logging.getLogger("gentlebot.worker")

WORKER_CLAIM_BATCH = 10
CLAIM_LEASE_TIMEOUT = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _release_stale_claims(session: Session, worker_id: str, now: datetime) -> int:
    """Re-enqueue ``running`` occurrences whose leases have expired."""

    lease_deadline = now - CLAIM_LEASE_TIMEOUT
    stmt = (
        update(TaskOccurrence)
        .where(TaskOccurrence.state == OccurrenceState.RUNNING)
        .where(TaskOccurrence.locked_at.is_not(None))
        .where(TaskOccurrence.locked_at <= lease_deadline)
        .values(
            state=OccurrenceState.ENQUEUED,
            enqueued_at=now,
            locked_by=None,
            locked_at=None,
            updated_at=now,
        )
    )
    result = session.execute(stmt)
    rowcount = result.rowcount if result.rowcount is not None else 0
    reclaimed = max(rowcount, 0)
    if reclaimed:
        log.warning(
            "re-enqueued stale running occurrences",
            extra={
                "count": reclaimed,
                "worker_id": worker_id,
                "lease_seconds": int(CLAIM_LEASE_TIMEOUT.total_seconds()),
            },
        )
    return reclaimed


def _claim_occurrences(session: Session, worker_id: str, limit: int, now: datetime) -> List[ClaimedOccurrence]:
    """Claim a batch of occurrences using SKIP LOCKED when available."""

    claimed: List[ClaimedOccurrence] = []
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        stmt = text(
            """
            WITH cte AS (
              SELECT id FROM task_occurrence
              WHERE state='enqueued' AND (enqueued_at IS NULL OR enqueued_at <= :now)
              ORDER BY scheduled_for
              FOR UPDATE SKIP LOCKED
              LIMIT :limit
            )
            UPDATE task_occurrence o
            SET state='running', locked_by=:worker_id, locked_at=:now, updated_at=:now
            FROM cte WHERE o.id = cte.id
            RETURNING o.id, o.task_id
            """
        )
        rows = session.execute(stmt, {"limit": limit, "worker_id": worker_id, "now": now}).all()
        claimed = [ClaimedOccurrence(id=row.id, task_id=row.task_id) for row in rows]
        return claimed

    query = (
        select(TaskOccurrence)
        .where(TaskOccurrence.state == OccurrenceState.ENQUEUED)
        .where((TaskOccurrence.enqueued_at.is_(None)) | (TaskOccurrence.enqueued_at <= now))
        .order_by(TaskOccurrence.scheduled_for)
        .limit(limit)
    )
    occurrences = session.scalars(query).all()
    for occurrence in occurrences:
        occurrence.mark_running(worker_id, now)
        claimed.append(ClaimedOccurrence(id=occurrence.id, task_id=occurrence.task_id))
    session.flush()
    return claimed


def _within_concurrency(session: Session, task: ScheduledTask, occurrence: TaskOccurrence, worker_id: str) -> bool:
    if task.concurrency_limit <= 0:
        return True
    running = session.scalar(
        select(func.count()).select_from(TaskOccurrence).where(
            TaskOccurrence.task_id == task.id,
            TaskOccurrence.state == OccurrenceState.RUNNING,
            TaskOccurrence.id != occurrence.id,
            TaskOccurrence.locked_by != worker_id,
        )
    )
    return (running or 0) < task.concurrency_limit


def _compute_backoff_seconds(policy: dict, attempt_no: int) -> float:
    base = float(policy.get("base_seconds", 30))
    style = policy.get("backoff", "exponential")
    if style == "exponential":
        delay = base * (2 ** max(attempt_no - 1, 0))
    else:
        delay = base
    jitter = random.uniform(0, base)
    return delay + jitter


def _schedule_retry(
    occurrence: TaskOccurrence,
    task: ScheduledTask,
    attempt_no: int,
    finished_at: datetime,
    message: str,
) -> None:
    policy = task.retry_policy or {}
    max_attempts = int(policy.get("max_attempts", 3))
    if attempt_no >= max_attempts:
        occurrence.mark_failed(message)
        return
    delay_seconds = _compute_backoff_seconds(policy, attempt_no)
    next_available = finished_at + timedelta(seconds=delay_seconds)
    occurrence.mark_enqueued_for_retry(next_available, message)


def _process_occurrence(
    occurrence_id: int,
    worker_id: str,
    resolver: Callable[[str], HandlerProtocol],
    session_factory: sessionmaker[Session],
) -> int:
    with session_scope(session_factory) as session:
        occurrence = session.get(TaskOccurrence, occurrence_id)
        if occurrence is None:
            return 0
        task = session.get(ScheduledTask, occurrence.task_id)
        if task is None:
            log.error("missing task for occurrence", extra={"occurrence_id": occurrence.id})
            occurrence.mark_failed("task missing")
            return 0
        if occurrence.state != OccurrenceState.RUNNING:
            return 0
        if not _within_concurrency(session, task, occurrence, worker_id):
            occurrence.mark_enqueued_for_retry(_now() + timedelta(seconds=1), "concurrency_limit")
            return 0

        started_at = _now()
        attempt_no = (
            session.scalar(
                select(func.max(TaskExecution.attempt_no)).where(TaskExecution.occurrence_id == occurrence.id)
            )
            or 0
        ) + 1
        execution = TaskExecution(
            task_id=task.id,
            occurrence_id=occurrence.id,
            attempt_no=attempt_no,
            trigger_type="retry" if attempt_no > 1 else "schedule",
            status="running",
            worker_id=worker_id,
            started_at=started_at,
        )
        session.add(execution)
        session.flush()

        ctx = {
            "occurrence_id": occurrence.id,
            "task_id": task.id,
            "name": task.name,
            "scheduled_for": occurrence.scheduled_for,
            "now": started_at,
        }
        payload = dict(task.payload or {})

        try:
            handler = resolver(task.handler)
            result = handler(ctx, payload)
        except RetryableError as exc:  # pragma: no cover - tested via retry flow
            finished_at = _now()
            execution.status = "failed"
            execution.finished_at = finished_at
            execution.error = {"type": "retryable", "message": str(exc)}
            _schedule_retry(occurrence, task, attempt_no, finished_at, str(exc))
            task.mark_run("failed", finished_at)
            log.warning(
                "handler requested retry",
                extra={
                    "task_id": task.id,
                    "occurrence_id": occurrence.id,
                    "attempt": attempt_no,
                    "worker_id": worker_id,
                    "error": str(exc),
                },
            )
        except FatalError as exc:
            finished_at = _now()
            execution.status = "failed"
            execution.finished_at = finished_at
            execution.error = {"type": "fatal", "message": str(exc)}
            occurrence.mark_failed(str(exc))
            task.mark_run("failed", finished_at)
            log.error(
                "handler fatal error",
                extra={
                    "task_id": task.id,
                    "occurrence_id": occurrence.id,
                    "attempt": attempt_no,
                    "worker_id": worker_id,
                    "error": str(exc),
                },
            )
        except Exception as exc:  # pragma: no cover - safety net
            finished_at = _now()
            execution.status = "failed"
            execution.finished_at = finished_at
            execution.error = {"type": exc.__class__.__name__, "message": str(exc)}
            occurrence.mark_failed(str(exc))
            task.mark_run("failed", finished_at)
            log.exception(
                "unhandled handler error",
                extra={
                    "task_id": task.id,
                    "occurrence_id": occurrence.id,
                    "attempt": attempt_no,
                    "worker_id": worker_id,
                },
            )
        else:
            finished_at = _now()
            execution.status = "succeeded"
            execution.finished_at = finished_at
            execution.result = result
            occurrence.mark_executed(finished_at)
            task.mark_run("succeeded", finished_at)
            log.info(
                "handler succeeded",
                extra={
                    "task_id": task.id,
                    "occurrence_id": occurrence.id,
                    "attempt": attempt_no,
                    "worker_id": worker_id,
                },
            )
        finally:
            session.flush()
    return 1


def run_worker_cycle(
    worker_id: str,
    *,
    session_factory: sessionmaker[Session] = SessionLocal,
    resolver: Callable[[str], HandlerProtocol] = resolve_handler,
    now: Optional[datetime] = None,
) -> int:
    """Claim and process a batch of occurrences."""

    now = now or _now()
    with session_scope(session_factory) as session:
        _release_stale_claims(session, worker_id, now)
        claimed = _claim_occurrences(session, worker_id, WORKER_CLAIM_BATCH, now)
    processed = 0
    for claim in claimed:
        processed += _process_occurrence(claim.id, worker_id, resolver, session_factory)
    return processed


__all__ = ["run_worker_cycle", "WORKER_CLAIM_BATCH", "CLAIM_LEASE_TIMEOUT"]
