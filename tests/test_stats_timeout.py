import asyncio
import requests

from gentlebot.cogs.bigdumper_watcher_cog import BigDumperWatcherCog
from gentlebot.cogs.mariners_game_cog import MarinersGameCog
from gentlebot.cogs.sports_cog import STATS_TIMEOUT


def test_session_timeout_default():
    async def run_test():
        cog = BigDumperWatcherCog(bot=None)
        assert cog.session.timeout.total == STATS_TIMEOUT
        await cog.session.close()

    asyncio.run(run_test())


def test_fetch_game_summary_uses_timeout(monkeypatch):
    cog = MarinersGameCog(bot=None)
    timeouts: list[float | None] = []

    class DummyResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"dates": []}

    class DummySession:
        def __enter__(self) -> "DummySession":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def mount(self, *args, **kwargs) -> None:
            return None

        def get(self, url, timeout=None):
            timeouts.append(timeout)
            return DummyResp()

    monkeypatch.setattr(requests, "Session", lambda: DummySession())
    assert cog.fetch_game_summary() is None
    assert timeouts and all(t == STATS_TIMEOUT for t in timeouts)
