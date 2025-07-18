import asyncio
import logging
import asyncpg
from postgres_handler import PostgresHandler

class DummyPool:
    def __init__(self) -> None:
        self.records = []

    async def close(self):
        pass

    async def execute(self, *args, **kwargs):
        self.executed = True

    async def copy_records_to_table(self, table: str, records: list, columns: list[str]):
        self.records.extend(records)

async def fake_create_pool(url, *args, **kwargs):
    assert url.startswith("postgresql://")
    return DummyPool()

def test_dsn_conversion(monkeypatch):
    async def run_test():
        monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)
        handler = PostgresHandler("postgresql+asyncpg://u:p@localhost/db")
        await handler.connect()
        await handler.aclose()

    asyncio.run(run_test())


def test_debug_logs_filtered(monkeypatch):
    async def run_test():
        pool = DummyPool()
        handler = PostgresHandler("postgresql+asyncpg://u:p@localhost/db")
        handler.pool = pool
        handler._queue = asyncio.Queue()
        logger = logging.getLogger("gentlebot.test")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        logger.debug("debug message")
        logger.removeHandler(handler)
        await asyncio.sleep(0)
        assert not getattr(pool, "executed", False)
        assert not pool.records

    asyncio.run(run_test())


def test_emit_batching(monkeypatch):
    async def run_test():
        pool = DummyPool()
        async def fake_pool(*args, **kwargs):
            return pool

        monkeypatch.setattr(asyncpg, "create_pool", fake_pool)
        handler = PostgresHandler(
            "postgresql+asyncpg://u:p@localhost/db", batch_size=2, flush_interval=0.05
        )
        await handler.connect()
        logger = logging.getLogger("gentlebot.batch")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.info("one")
        logger.info("two")
        await asyncio.sleep(0.1)
        logger.removeHandler(handler)
        await handler.aclose()
        assert len(pool.records) == 2

    asyncio.run(run_test())
