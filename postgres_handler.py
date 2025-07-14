import asyncio
import logging
from datetime import datetime, timezone

import asyncpg

class PostgresHandler(logging.Handler):
    """Asynchronously insert log records into Postgres."""

    def __init__(self, dsn: str, table: str = "bot_logs") -> None:
        super().__init__()
        self.dsn = dsn
        self.table = table
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None

    def emit(self, record: logging.LogRecord) -> None:
        if not self.pool:
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
        asyncio.create_task(coro)
