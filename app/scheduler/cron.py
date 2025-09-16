"""Cron and recurrence helpers for the scheduler."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from croniter import croniter
from zoneinfo import ZoneInfo


class UnsupportedScheduleError(RuntimeError):
    """Raised when a schedule kind is not yet implemented."""


def _ensure_aware(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def compute_due_times(
    schedule_kind: str,
    schedule_expr: str,
    timezone_name: str,
    window_start: datetime,
    window_end: datetime,
) -> List[datetime]:
    """Return UTC datetimes that fall within the provided window."""

    if schedule_kind != "CRON":
        raise UnsupportedScheduleError(schedule_kind)

    start_utc = _ensure_aware(window_start)
    end_utc = _ensure_aware(window_end)

    tz = ZoneInfo(timezone_name)
    start_local = start_utc.astimezone(tz)
    end_local = end_utc.astimezone(tz)

    iterator = croniter(schedule_expr, start_local - timedelta(seconds=1))
    due: List[datetime] = []
    while True:
        next_local = iterator.get_next(datetime)
        if next_local > end_local:
            break
        if next_local < start_local:
            continue
        if not croniter.match(schedule_expr, next_local):
            continue
        due.append(next_local.astimezone(timezone.utc))
    return due


def compute_next_run_after(
    schedule_kind: str,
    schedule_expr: str,
    timezone_name: str,
    reference: datetime,
) -> datetime:
    """Return the next run timestamp strictly after the reference time."""

    if schedule_kind != "CRON":
        raise UnsupportedScheduleError(schedule_kind)

    reference = _ensure_aware(reference)
    tz = ZoneInfo(timezone_name)
    reference_local = reference.astimezone(tz)
    iterator = croniter(schedule_expr, reference_local)
    next_local = iterator.get_next(datetime)
    return next_local.astimezone(timezone.utc)


__all__ = ["compute_due_times", "compute_next_run_after", "UnsupportedScheduleError"]
