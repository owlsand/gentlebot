"""SQLAlchemy model for scheduled tasks."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base, JSONDict, BIGINT_PK, utcnow


try:  # pragma: no cover - optional import during sqlite tests
    from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
except ImportError:  # pragma: no cover
    SQLITE_JSON = None


def _json_type():
    """Return a JSONB type that gracefully falls back for SQLite."""

    jsonb = JSONB(astext_type=Text())
    if SQLITE_JSON is not None:
        return jsonb.with_variant(SQLITE_JSON(), "sqlite")
    return jsonb


DEFAULT_RETRY_POLICY: Dict[str, Any] = {
    "max_attempts": 3,
    "backoff": "exponential",
    "base_seconds": 30,
}


class ScheduledTask(Base):
    """Represents a logical task definition that can emit occurrences."""

    __tablename__ = "scheduled_task"
    __table_args__ = (
        CheckConstraint("schedule_kind IN ('CRON','ONE_SHOT','RRULE','INTERVAL')", name="scheduled_task_kind_chk"),
        CheckConstraint("status IN ('shadow','active','paused','canceled')", name="scheduled_task_status_chk"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    guild_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    owner_user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    handler: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[JSONDict] = mapped_column(_json_type(), default=dict, nullable=False)
    schedule_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    schedule_expr: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_run_status: Mapped[Optional[str]] = mapped_column(String(16))
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    retry_policy: Mapped[Dict[str, Any]] = mapped_column(_json_type(), default=lambda: DEFAULT_RETRY_POLICY.copy(), nullable=False)
    idempotency_scope: Mapped[Optional[str]] = mapped_column(String(255))

    occurrences = relationship(
        "TaskOccurrence", back_populates="task", cascade="all, delete-orphan"
    )
    executions = relationship("TaskExecution", back_populates="task")

    def touch_next_run(self, next_run_at: Optional[datetime]) -> None:
        """Update the next_run_at timestamp."""

        self.next_run_at = next_run_at
        self.updated_at = utcnow()

    def mark_run(self, status: str, when: Optional[datetime] = None) -> None:
        """Update bookkeeping fields after an execution attempt."""

        self.last_run_status = status
        self.last_run_at = when or utcnow()
        self.updated_at = utcnow()

    @classmethod
    def by_name(cls, session, name: str) -> Optional["ScheduledTask"]:
        return session.query(cls).filter(cls.name == name).one_or_none()

    @classmethod
    def create(
        cls,
        session,
        *,
        name: str,
        handler: str,
        schedule_kind: str,
        schedule_expr: str,
        timezone: str = "UTC",
        payload: Optional[Dict[str, Any]] = None,
        status: str = "shadow",
        is_active: bool = True,
        concurrency_limit: int = 1,
        retry_policy: Optional[Dict[str, Any]] = None,
        idempotency_scope: Optional[str] = None,
    ) -> "ScheduledTask":
        payload = payload or {}
        retry_policy = retry_policy or DEFAULT_RETRY_POLICY.copy()
        task = cls(
            name=name,
            handler=handler,
            schedule_kind=schedule_kind,
            schedule_expr=schedule_expr,
            timezone=timezone,
            payload=payload,
            status=status,
            is_active=is_active,
            concurrency_limit=concurrency_limit,
            retry_policy=retry_policy,
            idempotency_scope=idempotency_scope,
        )
        session.add(task)
        return task

    def activate(self) -> None:
        self.status = "active"
        self.is_active = True
        self.updated_at = utcnow()

    def pause(self) -> None:
        self.status = "paused"
        self.updated_at = utcnow()

    def shadow(self) -> None:
        self.status = "shadow"
        self.updated_at = utcnow()

    def cancel(self) -> None:
        self.status = "canceled"
        self.is_active = False
        self.updated_at = utcnow()


__all__ = ["ScheduledTask", "DEFAULT_RETRY_POLICY"]
