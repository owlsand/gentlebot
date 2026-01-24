"""Simple exponential backoff helpers for sync and async operations."""
from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from typing import Any, Callable, TypeVar

log = logging.getLogger(f"gentlebot.{__name__}")

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])


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
            # Only retry on a small set of transient HTTP errors.
            if status not in {408, 409} and not (status and 500 <= status < 600):
                raise
            # Bail out if we've exhausted all retry attempts.
            if attempt == retries:
                raise
            delay = min(max_delay, base * (2 ** attempt))
            delay += random.uniform(0, 0.1)
            time.sleep(delay)
    # Should be unreachable because either fn() succeeds or an exception is raised.
    raise RuntimeError("call_with_backoff reached an unreachable state")


async def async_retry(
    fn: Callable[[], T],
    retries: int = 3,
    base: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[Exception], ...] | None = None,
) -> T:
    """Call async *fn* with exponential backoff on transient errors.

    Args:
        fn: Async callable to execute.
        retries: Maximum number of retry attempts.
        base: Base delay in seconds for exponential backoff.
        max_delay: Maximum delay between retries.
        retry_on: Tuple of exception types to retry on. If None, retries on
            all exceptions.

    Returns:
        The result of the function call.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await fn()
        except Exception as exc:
            last_exc = exc
            # Check if we should retry this exception type
            if retry_on is not None and not isinstance(exc, retry_on):
                raise
            # Check for HTTP status codes on responses
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None:
                # Only retry on transient HTTP errors
                if status not in {408, 409, 429} and not (500 <= status < 600):
                    raise
            # Bail out if we've exhausted all retry attempts
            if attempt == retries:
                raise
            delay = min(max_delay, base * (2 ** attempt))
            delay += random.uniform(0, 0.1)
            log.debug(
                "Retry %d/%d for %s after %.2fs: %s",
                attempt + 1,
                retries,
                getattr(fn, "__name__", "unknown"),
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    # Should be unreachable
    if last_exc:
        raise last_exc
    raise RuntimeError("async_retry reached an unreachable state")


def with_retry(
    retries: int = 3,
    base: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[Exception], ...] | None = None,
) -> Callable[[F], F]:
    """Decorator for async functions with automatic retry on transient errors.

    Args:
        retries: Maximum number of retry attempts.
        base: Base delay in seconds for exponential backoff.
        max_delay: Maximum delay between retries.
        retry_on: Tuple of exception types to retry on. If None, retries on
            transient HTTP errors (408, 409, 429, 5xx).

    Example::

        @with_retry(retries=3, base=1.0)
        async def fetch_data():
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    return await resp.json()

        @with_retry(retry_on=(asyncio.TimeoutError, ConnectionError))
        async def connect_to_service():
            ...

    Returns:
        Decorated function with retry behavior.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await async_retry(
                lambda: fn(*args, **kwargs),
                retries=retries,
                base=base,
                max_delay=max_delay,
                retry_on=retry_on,
            )

        return wrapper  # type: ignore[return-value]

    return decorator
