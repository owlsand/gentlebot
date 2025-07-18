import asyncio
import logging
from datetime import datetime, timezone

import asyncpg

class PostgresHandler(logging.Handler):
    """Asynchronously insert log records into Postgres in batches."""

    _STOP = object()

    def __init__(self, dsn: str, table: str = "bot_logs", *, batch_size: int = 100, flush_interval: float = 1.0) -> None:
        super().__init__()
        self.dsn = dsn
        self.table = table
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.pool: asyncpg.Pool | None = None
        self._queue: asyncio.Queue | None = None
        self._worker: asyncio.Task | None = None
        # Ignore DEBUG records so they are not written to the database
        self.setLevel(logging.INFO)

    async def connect(self) -> None:
        url = self.dsn.replace("postgresql+asyncpg://", "postgresql://")

        async def _init(conn: asyncpg.Connection) -> None:
            await conn.execute("SET search_path=discord,public")

        self.pool = await asyncpg.create_pool(url, init=_init)

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

        self._queue = asyncio.Queue()
        self._worker = asyncio.create_task(self._worker_loop())

    async def aclose(self) -> None:
        if self._worker and not self._worker.done():
            assert self._queue
            await self._queue.put(self._STOP)
            await self._worker
        self._worker = None
        self._queue = None
        if self.pool:
            await self.pool.close()
            self.pool = None

    def close(self) -> None:
        if self.pool or self._worker:
            try:
                asyncio.run(self.aclose())
            except RuntimeError:
                loop = asyncio.get_running_loop()
                loop.create_task(self.aclose())
        super().close()

    def emit(self, record: logging.LogRecord) -> None:
        if not self._queue:
            return
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc)
        message = record.getMessage()
        try:
            self._queue.put_nowait((record.name, record.levelname, message, ts))
        except asyncio.QueueFull:
            # Drop the log if the queue is full
            pass

    async def _flush(self, batch: list[tuple]) -> None:
        if not self.pool:
            return
        if hasattr(self.pool, "copy_records_to_table"):
            await self.pool.copy_records_to_table(
                self.table,
                records=batch,
                columns=["logger_name", "log_level", "message", "created_at"],
            )
        else:
            for rec in batch:
                await self.pool.execute(
                    f"INSERT INTO {self.table} (logger_name, log_level, message, created_at) VALUES ($1, $2, $3, $4)",
                    *rec,
                )

    async def _worker_loop(self) -> None:
        assert self._queue is not None
        batch: list[tuple] = []
        while True:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=self.flush_interval)
            except asyncio.TimeoutError:
                item = None
            if item is self._STOP:
                break
            if item is not None:
                batch.append(item)
            if item is None or len(batch) >= self.batch_size:
                if batch:
                    await self._flush(batch)
                    batch.clear()
        if batch:
            await self._flush(batch)
