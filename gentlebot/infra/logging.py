"""Standardized logging utilities for Gentlebot."""
from __future__ import annotations

import logging
from typing import Any

# Root logger name for all Gentlebot components
ROOT_LOGGER_NAME = "gentlebot"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a hierarchical logger under the gentlebot namespace.

    This ensures all loggers use consistent naming and can be configured
    together via the root "gentlebot" logger.

    Args:
        name: Module or component name. If None, returns the root logger.
              The name will be prefixed with "gentlebot." automatically
              if it doesn't already have that prefix.

    Returns:
        A configured Logger instance.

    Example::

        # In a module file:
        from gentlebot.infra.logging import get_logger
        log = get_logger(__name__)  # -> "gentlebot.gentlebot.cogs.my_cog"

        # Or with explicit name:
        log = get_logger("my_feature")  # -> "gentlebot.my_feature"
    """
    if name is None:
        return logging.getLogger(ROOT_LOGGER_NAME)

    # Remove any existing gentlebot prefix to avoid duplication
    clean_name = name
    if clean_name.startswith(f"{ROOT_LOGGER_NAME}."):
        clean_name = clean_name[len(ROOT_LOGGER_NAME) + 1 :]

    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{clean_name}")


def get_cog_logger(cog_name: str) -> logging.Logger:
    """Return a logger specifically for a cog.

    Args:
        cog_name: Name of the cog (class name or module name).

    Returns:
        A Logger instance under "gentlebot.cogs.<cog_name>".
    """
    return get_logger(f"cogs.{cog_name}")


class LogContext:
    """Context manager for temporarily adding context to log messages.

    This is useful for adding request-specific context to logs without
    modifying the logger configuration globally.

    Example::

        async def handle_request(self, user_id: int):
            with LogContext(log, user_id=user_id, action="process"):
                log.info("Starting request")  # Logs with context
                await self.do_work()
            # Context automatically removed after the block
    """

    def __init__(self, logger: logging.Logger, **context: Any) -> None:
        self.logger = logger
        self.context = context
        self._old_factory: Any = None

    def __enter__(self) -> "LogContext":
        old_factory = logging.getLogRecordFactory()
        context = self.context

        def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = old_factory(*args, **kwargs)
            for key, value in context.items():
                setattr(record, key, value)
            return record

        self._old_factory = old_factory
        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, *args: Any) -> None:
        if self._old_factory is not None:
            logging.setLogRecordFactory(self._old_factory)


def structured_log(
    logger: logging.Logger,
    level: int,
    message: str,
    **fields: Any,
) -> None:
    """Log a message with structured key=value fields appended.

    This provides a simple way to add structured context to log messages
    without requiring a full structured logging setup.

    Args:
        logger: Logger instance to use
        level: Logging level (e.g., logging.INFO)
        message: Base log message
        **fields: Key-value pairs to append to the message

    Example::

        structured_log(log, logging.INFO, "Request completed",
                      user_id=123, duration_ms=45, status="ok")
        # Logs: "Request completed user_id=123 duration_ms=45 status=ok"
    """
    if fields:
        field_str = " ".join(f"{k}={v}" for k, v in fields.items())
        message = f"{message} {field_str}"
    logger.log(level, message)
