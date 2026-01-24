import asyncio
import logging
from datetime import datetime, timezone

import asyncpg

from .db import get_pool

class PostgresHandler(logging.Handler):
    """Asynchronously insert log records into Postgres."""

    def __init__(self, dsn: str, table: str = "bot_logs") -> None:
        super().__init__()
        self.dsn = dsn
        self.table = table
        self.pool: asyncpg.Pool | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._owns_pool: bool = False  # Track whether we created our own pool
        # Ignore DEBUG records so they are not written to the database
        self.setLevel(logging.INFO)

    async def connect(self) -> None:
        # Use the shared pool if available, otherwise create our own
        try:
            self.pool = await get_pool()
            self._owns_pool = False
        except RuntimeError:
            # Fallback to creating own pool if get_pool() fails
            url = self.dsn.replace("postgresql+asyncpg://", "postgresql://")

            async def _init(conn: asyncpg.Connection) -> None:
                await conn.execute("SET search_path=discord,public")

            self.pool = await asyncpg.create_pool(
                url,
                init=_init,
                min_size=1,
                max_size=3,
                command_timeout=30,
                timeout=10,
            )
            self._owns_pool = True

        self.loop = asyncio.get_running_loop()

        create_sql = (
            f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                id SERIAL PRIMARY KEY,
                logger_name TEXT NOT NULL,
                log_level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_sql)
        except AttributeError:
            # tests may supply a simplified pool without 'acquire'
            await self.pool.execute(create_sql)

    async def aclose(self) -> None:
        if self.pool and self._owns_pool:
            await self.pool.close()
        self.pool = None

    def close(self) -> None:
        # Only close the pool if we own it (not using shared pool)
        if self.pool and self._owns_pool:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.pool.close())
            except RuntimeError:
                # No running loop, try to create one for cleanup
                try:
                    asyncio.get_event_loop().run_until_complete(self.pool.close())
                except Exception:
                    pass  # Best effort cleanup
        self.pool = None
        super().close()

    def emit(self, record: logging.LogRecord) -> None:
        if not self.pool or not self.loop:
            return
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc)
        message = record.getMessage()
        coro = self.pool.execute(
            f"INSERT INTO {self.table} (logger_name, log_level, message, created_at) VALUES ($1, $2, $3, $4)",
            record.name,
            record.levelname,
            message,
            ts,
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        else:
            if loop is self.loop:
                loop.create_task(coro)
            else:
                asyncio.run_coroutine_threadsafe(coro, self.loop)
