import asyncio
import logging
import asyncpg
from postgres_handler import PostgresHandler

class DummyPool:
    async def close(self):
        pass

    async def execute(self, *args, **kwargs):
        self.executed = True

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
        logger = logging.getLogger("gentlebot.test")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        logger.debug("debug message")
        logger.removeHandler(handler)
        await asyncio.sleep(0)
        assert not getattr(pool, "executed", False)

    asyncio.run(run_test())
