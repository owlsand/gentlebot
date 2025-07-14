import asyncio
import asyncpg
from postgres_handler import PostgresHandler

class DummyPool:
    async def close(self):
        pass

async def fake_create_pool(url):
    assert url.startswith("postgresql://")
    return DummyPool()

def test_dsn_conversion(monkeypatch):
    async def run_test():
        monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)
        handler = PostgresHandler("postgresql+asyncpg://u:p@localhost/db")
        await handler.connect()
        await handler.aclose()

    asyncio.run(run_test())
