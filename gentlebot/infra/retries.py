"""Simple exponential backoff helper."""
from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def call_with_backoff(
    fn: Callable[[], T],
    retries: int = 3,
    base: float = 0.5,
    max_delay: float = 8.0,
) -> T:
    """Call *fn* with exponential backoff on transient HTTP errors."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:  # pragma: no cover - network
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status not in {408, 409, 429} and not (status and 500 <= status < 600):
                raise
            delay = min(max_delay, base * (2 ** attempt))
            delay += random.uniform(0, 0.1)
            time.sleep(delay)
    return fn()
