"""SQLAlchemy model for task execution attempts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base, BIGINT_PK

try:  # pragma: no cover
    from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
except ImportError:  # pragma: no cover
    SQLITE_JSON = None


def _json_type():
    jsonb = JSONB(astext_type=Text())
    if SQLITE_JSON is not None:
        return jsonb.with_variant(SQLITE_JSON(), "sqlite")
    return jsonb


class TaskExecution(Base):
    """Tracks each attempt to execute a task occurrence."""

    __tablename__ = "task_execution"
    __table_args__ = (
        UniqueConstraint('occurrence_id', 'attempt_no', name='task_execution_attempt_uc'),
        CheckConstraint('attempt_no >= 1', name='task_execution_attempt_ck'),
        CheckConstraint("status IN ('queued','running','succeeded','failed','canceled','timed_out')", name='task_execution_status_ck'),
        CheckConstraint("trigger_type IN ('schedule','retry','manual')", name='task_execution_trigger_ck'),
        Index('task_execution_finished_idx', 'task_id', 'finished_at'),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("scheduled_task.id", ondelete="CASCADE"), nullable=False)
    occurrence_id: Mapped[int] = mapped_column(ForeignKey("task_occurrence.id", ondelete="CASCADE"), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(16), default="schedule", nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    worker_id: Mapped[Optional[str]] = mapped_column(String(64))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(_json_type())
    error: Mapped[Optional[Dict[str, Any]]] = mapped_column(_json_type())

    task = relationship("ScheduledTask", back_populates="executions")
    occurrence = relationship("TaskOccurrence", back_populates="executions")


__all__ = ["TaskExecution"]
