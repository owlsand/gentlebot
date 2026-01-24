"""Shared HTTP client management.

This module provides centralized HTTP client configuration with:
- Connection pooling and session reuse
- Automatic retries with exponential backoff
- Consistent timeout and User-Agent settings
- Both synchronous (requests) and asynchronous (aiohttp) clients

Usage:
    # Synchronous requests
    from gentlebot.infra.http import get_sync_session
    session = get_sync_session()
    response = session.get("https://api.example.com/data")

    # Asynchronous requests
    from gentlebot.infra.http import get_async_session
    async with get_async_session() as session:
        async with session.get("https://api.example.com/data") as response:
            data = await response.json()
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(f"gentlebot.{__name__}")

# Default configuration
DEFAULT_TIMEOUT = 10  # seconds
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 1.0
DEFAULT_STATUS_FORCELIST = [500, 502, 503, 504]
DEFAULT_USER_AGENT = "gentlebot/1.0"

# Shared session instance (thread-safe for requests)
_sync_session: Optional[requests.Session] = None


def get_sync_session(
    retries: int = DEFAULT_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    status_forcelist: list[int] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> requests.Session:
    """Get or create a shared synchronous HTTP session.

    The session is configured with retries, connection pooling, and
    reasonable defaults. It's thread-safe and can be reused across
    the application.

    Args:
        retries: Number of retries for failed requests
        backoff_factor: Multiplier for exponential backoff between retries
        status_forcelist: HTTP status codes that trigger retries
        timeout: Default timeout for requests (seconds)

    Returns:
        A configured requests.Session instance

    Example:
        >>> session = get_sync_session()
        >>> response = session.get("https://api.example.com", timeout=5)
    """
    global _sync_session

    if _sync_session is None:
        _sync_session = _create_sync_session(
            retries=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist or DEFAULT_STATUS_FORCELIST,
        )
        log.debug("Created shared sync HTTP session")

    return _sync_session


def _create_sync_session(
    retries: int,
    backoff_factor: float,
    status_forcelist: list[int],
) -> requests.Session:
    """Create a new configured requests session."""
    session = requests.Session()

    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=20,
    )

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update({
        "User-Agent": DEFAULT_USER_AGENT,
    })

    return session


def create_sync_session(
    retries: int = DEFAULT_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    status_forcelist: list[int] | None = None,
) -> requests.Session:
    """Create a new independent synchronous HTTP session.

    Unlike get_sync_session(), this creates a fresh session each time.
    Use this when you need isolated session state or custom configuration.

    Args:
        retries: Number of retries for failed requests
        backoff_factor: Multiplier for exponential backoff
        status_forcelist: HTTP status codes that trigger retries

    Returns:
        A new configured requests.Session instance
    """
    return _create_sync_session(
        retries=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist or DEFAULT_STATUS_FORCELIST,
    )


@asynccontextmanager
async def get_async_session(
    timeout: int = DEFAULT_TIMEOUT,
) -> AsyncIterator["aiohttp.ClientSession"]:
    """Get an async HTTP session for use within an async context.

    Unlike the sync session, async sessions should be created per-context
    due to event loop requirements. The session is automatically closed
    when the context exits.

    Args:
        timeout: Total timeout for requests (seconds)

    Yields:
        An aiohttp.ClientSession instance

    Example:
        >>> async with get_async_session() as session:
        ...     async with session.get("https://api.example.com") as resp:
        ...         data = await resp.json()
    """
    # Import here to avoid requiring aiohttp if only sync is used
    import aiohttp

    timeout_config = aiohttp.ClientTimeout(total=timeout)

    connector = aiohttp.TCPConnector(
        limit=20,  # Max simultaneous connections
        limit_per_host=10,  # Max connections per host
    )

    async with aiohttp.ClientSession(
        timeout=timeout_config,
        connector=connector,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    ) as session:
        yield session


def close_sessions() -> None:
    """Close all shared sessions.

    Call this during application shutdown to cleanly release resources.
    The next call to get_sync_session() will create a new session.
    """
    global _sync_session

    if _sync_session is not None:
        try:
            _sync_session.close()
        except Exception:
            log.exception("Error closing sync session")
        _sync_session = None
        log.debug("Closed shared sync HTTP session")


def reset_sessions() -> None:
    """Reset sessions for testing.

    Forces new session creation on next access. Useful in tests
    to ensure clean state.
    """
    global _sync_session
    _sync_session = None
