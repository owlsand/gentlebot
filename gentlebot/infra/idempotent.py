"""Idempotency decorator for scheduled tasks.

This module provides a decorator that ensures scheduled tasks are only
executed once per execution key (e.g., date, week number), preventing
duplicate operations after bot restarts or crashes.
"""
from __future__ import annotations

import functools
import logging
from datetime import date
from typing import Any, Callable, TypeVar

import asyncpg

log = logging.getLogger(f"gentlebot.{__name__}")

F = TypeVar("F", bound=Callable[..., Any])


async def _already_executed(pool: asyncpg.Pool, task_name: str, key: str) -> bool:
    """Check if a task has already been executed with the given key."""
    row = await pool.fetchval(
        """
        SELECT 1 FROM discord.task_execution
        WHERE task_name = $1 AND execution_key = $2
        """,
        task_name,
        key,
    )
    return row is not None


async def _mark_executed(
    pool: asyncpg.Pool,
    task_name: str,
    key: str,
    result: str | None = None,
) -> None:
    """Mark a task as executed with the given key."""
    await pool.execute(
        """
        INSERT INTO discord.task_execution (task_name, execution_key, result)
        VALUES ($1, $2, $3)
        ON CONFLICT (task_name, execution_key) DO UPDATE SET
            executed_at = now(),
            result = EXCLUDED.result
        """,
        task_name,
        key,
        result,
    )


def idempotent_task(
    task_name: str,
    key_func: Callable[..., str],
    pool_attr: str = "pool",
) -> Callable[[F], F]:
    """Decorator preventing duplicate task execution.

    This decorator wraps async methods that should only run once per
    execution key. It checks a database table to see if the task has
    already been executed with the computed key, and skips execution
    if so.

    Args:
        task_name: Unique name identifying this task in the execution log.
        key_func: Function that computes the execution key from the method's
            arguments. Should return a string that uniquely identifies this
            execution window (e.g., today's date, week number).
        pool_attr: Name of the attribute on `self` that holds the asyncpg pool.
            Defaults to "pool".

    Example::

        class DailyTaskCog(commands.Cog):
            def __init__(self, bot):
                self.pool = None  # Set during cog_load

            @idempotent_task("daily_digest", lambda self: date.today().isoformat())
            async def _run_digest(self):
                # This will only run once per day
                ...

        class WeeklyTaskCog(commands.Cog):
            @idempotent_task(
                "weekly_recap",
                lambda self, week: f"{date.today().year}-W{week:02d}"
            )
            async def _post_recap(self, week: int):
                ...

    Returns:
        Decorated function that checks for prior execution before running.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            pool = getattr(self, pool_attr, None)
            if not pool:
                log.warning(
                    "idempotent_task %s: no pool available, running without idempotency",
                    task_name,
                )
                return await fn(self, *args, **kwargs)

            try:
                key = key_func(self, *args, **kwargs)
            except Exception:
                log.exception(
                    "idempotent_task %s: failed to compute execution key",
                    task_name,
                )
                return await fn(self, *args, **kwargs)

            try:
                if await _already_executed(pool, task_name, key):
                    log.info(
                        "idempotent_task %s: skipping, already executed for key=%s",
                        task_name,
                        key,
                    )
                    return None
            except Exception:
                log.exception(
                    "idempotent_task %s: failed to check execution status",
                    task_name,
                )
                # Proceed with execution on check failure to avoid missing tasks

            result = await fn(self, *args, **kwargs)

            try:
                result_str = str(result) if result is not None else None
                if result_str and len(result_str) > 500:
                    result_str = result_str[:500] + "..."
                await _mark_executed(pool, task_name, key, result_str)
                log.info(
                    "idempotent_task %s: marked as executed for key=%s",
                    task_name,
                    key,
                )
            except Exception:
                log.exception(
                    "idempotent_task %s: failed to mark as executed",
                    task_name,
                )

            return result

        return wrapper  # type: ignore[return-value]

    return decorator


def daily_key(self: Any) -> str:
    """Key function for daily tasks: returns today's ISO date."""
    return date.today().isoformat()


def weekly_key(self: Any) -> str:
    """Key function for weekly tasks: returns year-week string."""
    today = date.today()
    return f"{today.year}-W{today.isocalendar()[1]:02d}"


def monthly_key(self: Any) -> str:
    """Key function for monthly tasks: returns year-month of the previous month.

    This is used for tasks that run at the beginning of a month and process
    data from the previous month (e.g., monthly recaps).
    """
    from datetime import timedelta

    today = date.today()
    first_of_month = today.replace(day=1)
    prev_month = first_of_month - timedelta(days=1)
    return f"{prev_month.year}-{prev_month.month:02d}"
