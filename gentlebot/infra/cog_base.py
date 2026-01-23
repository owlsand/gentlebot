"""Base classes and mixins for Discord cogs."""
from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any, Callable, TypeVar

import asyncpg
from discord.ext import commands

from ..db import get_pool

if TYPE_CHECKING:
    from discord.ext.commands import Bot

log = logging.getLogger(f"gentlebot.{__name__}")

F = TypeVar("F", bound=Callable[..., Any])


class PoolAwareCog(commands.Cog):
    """Mixin providing standardized database pool initialization.

    Subclasses automatically get a ``self.pool`` attribute that is
    initialized during ``cog_load()`` and cleared during ``cog_unload()``.
    The pool is shared across all cogs via the global ``get_pool()`` helper.

    If the database URL is missing, the cog will log a warning and set
    ``self.pool`` to ``None``. Subclasses can check this to disable
    database-dependent functionality gracefully.

    Example::

        class MyCog(PoolAwareCog):
            async def some_command(self, ctx):
                if not self.pool:
                    return await ctx.send("Database unavailable")
                rows = await self.pool.fetch("SELECT ...")
    """

    pool: asyncpg.Pool | None = None

    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        self.pool = None

    async def cog_load(self) -> None:
        """Initialize the database pool.

        Subclasses that override this method should call ``await super().cog_load()``
        to ensure the pool is properly initialized.
        """
        try:
            self.pool = await get_pool()
        except RuntimeError:
            self.pool = None
            log.warning(
                "%s: database pool unavailable (PG_DSN missing)",
                self.__class__.__name__,
            )

    async def cog_unload(self) -> None:
        """Clear the pool reference.

        Subclasses that override this method should call ``await super().cog_unload()``
        to ensure proper cleanup.
        """
        self.pool = None

    @property
    def has_pool(self) -> bool:
        """Return True if the database pool is available."""
        return self.pool is not None


def require_pool(func: F) -> F:
    """Decorator that skips execution if the cog has no database pool.

    Use this on cog methods that require database access. If the pool
    is unavailable, the method returns None without executing.

    Example::

        @require_pool
        async def on_message(self, message):
            # This only runs if self.pool is available
            await self.pool.execute(...)
    """

    @functools.wraps(func)
    async def wrapper(self: PoolAwareCog, *args: Any, **kwargs: Any) -> Any:
        if not getattr(self, "pool", None):
            return None
        return await func(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


def log_errors(
    message: str = "Operation failed",
    *,
    reraise: bool = False,
    return_value: Any = None,
) -> Callable[[F], F]:
    """Decorator that logs exceptions with consistent formatting.

    Args:
        message: Log message prefix for the error
        reraise: If True, re-raise the exception after logging
        return_value: Value to return if an exception occurs (when not reraising)

    Example::

        @log_errors("Failed to process message")
        async def on_message(self, message):
            ...

        @log_errors("Critical operation", reraise=True)
        async def critical_task(self):
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception:
                # Get the logger for the module where the decorated function lives
                func_log = logging.getLogger(f"gentlebot.{func.__module__}")
                func_log.exception("%s in %s", message, func.__name__)
                if reraise:
                    raise
                return return_value

        return wrapper  # type: ignore[return-value]

    return decorator
