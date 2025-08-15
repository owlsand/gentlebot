import asyncio
import logging
import asyncpg
from gentlebot.postgres_handler import PostgresHandler

class DummyPool:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True

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
        handler.loop = asyncio.get_running_loop()
        logger = logging.getLogger("gentlebot.test")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        logger.debug("debug message")
        logger.removeHandler(handler)
        await asyncio.sleep(0)
        assert not getattr(pool, "executed", False)

    asyncio.run(run_test())


def test_emit_threadsafe():
    async def run_test():
        pool = DummyPool()
        handler = PostgresHandler("postgresql+asyncpg://u:p@localhost/db")
        handler.pool = pool
        handler.loop = asyncio.get_running_loop()

        record = logging.LogRecord(
            name="gentlebot.test", level=logging.INFO, pathname="", lineno=0, msg="hello", args=(), exc_info=None
        )

        import threading

        def emit_in_thread():
            handler.emit(record)

        t = threading.Thread(target=emit_in_thread)
        t.start()
        t.join()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert getattr(pool, "executed", False)

    asyncio.run(run_test())


def test_close_asyncio_run_not_called(monkeypatch):
    async def run_test():
        pool = DummyPool()
        handler = PostgresHandler("postgresql+asyncpg://u:p@localhost/db")
        handler.pool = pool

        called = False

        def fake_run(*args, **kwargs):
            nonlocal called
            called = True
            raise RuntimeError("unexpected call")

        monkeypatch.setattr(asyncio, "run", fake_run)

        handler.close()
        await asyncio.sleep(0)

        assert pool.closed
        assert not called

    asyncio.run(run_test())
