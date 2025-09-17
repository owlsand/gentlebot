"""Shared Postgres connection pool for Gentlebot."""
from __future__ import annotations

import logging

import asyncpg

from .util import build_db_url

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Return a global asyncpg pool, creating it if needed."""
    global _pool
    if _pool:
        # ``asyncpg`` marks pools as closing/closed after :meth:`close` is awaited.
        # Some cogs previously called ``close()`` on the shared pool which left the
        # cached instance pointing at a closed pool.  Guard against that situation
        # so we can transparently rebuild the pool when needed.
        try:
            if not _pool.is_closing():
                return _pool
        except AttributeError:  # pragma: no cover - defensive for unexpected pool
            return _pool
        _pool = None
    url = build_db_url()
    if not url:
        raise RuntimeError("PG_DSN is missing")
    url = url.replace("postgresql+asyncpg://", "postgresql://")

    async def _init(conn: asyncpg.Connection) -> None:
        await conn.execute("SET search_path=discord,public")

    _pool = await asyncpg.create_pool(url, init=_init)
    return _pool


async def close_pool() -> None:
    """Close the global pool if it exists."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
