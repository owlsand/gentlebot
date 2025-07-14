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
        # Ignore DEBUG records so they are not written to the database
        self.setLevel(logging.INFO)

    async def connect(self) -> None:
        url = self.dsn.replace("postgresql+asyncpg://", "postgresql://")
        self.pool = await asyncpg.create_pool(url)

    async def aclose(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None

    def close(self) -> None:
        if self.pool:
            try:
                asyncio.run(self.pool.close())
            except RuntimeError:
                loop = asyncio.get_running_loop()
                loop.create_task(self.pool.close())
            self.pool = None
        super().close()

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
