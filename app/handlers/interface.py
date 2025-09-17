"""Handler contract for scheduler task execution."""
from __future__ import annotations

import importlib
from datetime import datetime
from typing import Any, Dict, Protocol, TypedDict


class RetryableError(Exception):
    """Raised by handlers to request a retry with backoff."""


class FatalError(Exception):
    """Raised by handlers to signal unrecoverable failures."""


class TaskContext(TypedDict):
    occurrence_id: int
    task_id: int
    name: str
    scheduled_for: datetime
    now: datetime


class HandlerProtocol(Protocol):
    def __call__(self, ctx: TaskContext, payload: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - structural typing
        ...


def resolve_handler(handler_path: str) -> HandlerProtocol:
    """Resolve a handler string to the ``run_task`` callable."""

    try:
        module = importlib.import_module(handler_path)
    except ModuleNotFoundError:
        module = importlib.import_module(f"app.handlers.{handler_path}")
    if not hasattr(module, "run_task"):
        raise AttributeError(f"Handler module {module.__name__} missing run_task")
    return getattr(module, "run_task")


__all__ = ["RetryableError", "FatalError", "TaskContext", "HandlerProtocol", "resolve_handler"]
