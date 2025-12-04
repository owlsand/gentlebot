"""SQLAlchemy model and helpers for task occurrences."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base, BIGINT_PK, utcnow


class OccurrenceState:
    SCHEDULED = "scheduled"
    ENQUEUED = "enqueued"
    RUNNING = "running"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELED = "canceled"
    SKIPPED = "skipped"


@dataclass
class ClaimedOccurrence:
    """Representation returned after claiming work from the queue."""

    id: int
    task_id: int


class TaskOccurrence(Base):
    """Represents a single scheduled fire of a task."""

    __tablename__ = "task_occurrence"
    __table_args__ = (
        UniqueConstraint('task_id', 'occurrence_key', name='task_occurrence_key_uc'),
        Index('task_occurrence_task_time_idx', 'task_id', 'scheduled_for'),
        Index(
            'task_occurrence_executed_idx',
            'task_id',
            'state',
            postgresql_where=text("state IN ('executed','failed','skipped')"),
            sqlite_where=text("state IN ('executed','failed','skipped')"),
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("scheduled_task.id", ondelete="CASCADE"), nullable=False)
    occurrence_key: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    enqueued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), default=OccurrenceState.SCHEDULED, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    locked_by: Mapped[Optional[str]] = mapped_column(String(64))
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    task = relationship("ScheduledTask", back_populates="occurrences")
    executions = relationship("TaskExecution", back_populates="occurrence", cascade="all, delete-orphan")

    @staticmethod
    def compute_occurrence_key(
        task_id: int,
        schedule_kind: str,
        schedule_expr: str,
        scheduled_for: datetime,
        idempotency_scope: Optional[str],
    ) -> str:
        """Derive a deterministic occurrence key for upsert semantics."""

        scheduled_iso = scheduled_for.astimezone(timezone.utc).isoformat()
        scope = idempotency_scope or ""
        payload = f"{task_id}|{schedule_kind}|{schedule_expr}|{scheduled_iso}|{scope}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def mark_enqueued(self, when: datetime) -> None:
        self.state = OccurrenceState.ENQUEUED
        self.enqueued_at = when
        self.updated_at = utcnow()

    def mark_running(self, worker_id: str, when: datetime) -> None:
        self.state = OccurrenceState.RUNNING
        self.locked_by = worker_id
        self.locked_at = when
        self.updated_at = utcnow()

    def mark_executed(self, when: Optional[datetime] = None) -> None:
        when = when or utcnow()
        self.state = OccurrenceState.EXECUTED
        self.executed_at = self.executed_at or when
        self.locked_by = None
        self.locked_at = None
        self.updated_at = utcnow()

    def mark_failed(self, reason: Optional[str] = None) -> None:
        self.state = OccurrenceState.FAILED
        self.reason = reason
        self.locked_by = None
        self.locked_at = None
        self.updated_at = utcnow()

    def mark_enqueued_for_retry(self, when: datetime, reason: Optional[str] = None) -> None:
        self.state = OccurrenceState.ENQUEUED
        self.reason = reason
        self.locked_by = None
        self.locked_at = None
        self.enqueued_at = when
        self.updated_at = utcnow()


__all__ = ["TaskOccurrence", "OccurrenceState", "ClaimedOccurrence"]
