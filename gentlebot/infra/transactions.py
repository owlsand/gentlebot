"""Transaction helpers for Gentlebot database operations."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg


@asynccontextmanager
async def transaction(pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Connection]:
    """Context manager for database transactions.

    Acquires a connection from the pool and wraps operations in a transaction.
    The transaction is automatically committed on success or rolled back on error.

    Example::

        async with transaction(pool) as conn:
            await conn.execute("INSERT INTO ...")
            await conn.execute("UPDATE ...")
            # Both operations commit together or rollback together

    Args:
        pool: The asyncpg connection pool.

    Yields:
        An asyncpg Connection within a transaction context.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn
