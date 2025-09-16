from gentlebot.cogs.sports_cog import SportsCog, STATS_TIMEOUT


def test_session_timeout_default():
    async def run_test():
        cog = BigDumperWatcherCog(bot=None)
        assert cog.session.timeout.total == STATS_TIMEOUT
        await cog.session.close()

    asyncio.run(run_test())


def test_fetch_season_stats_uses_timeout(monkeypatch):
    cog = SportsCog(bot=None)
    called = {}

        def mount(self, *args, **kwargs) -> None:
            return None

        def get(self, url, timeout=None):
            timeouts.append(timeout)
            return DummyResp()

    monkeypatch.setattr(requests, "Session", lambda: DummySession())
    assert cog.fetch_game_summary() is None
    assert timeouts and all(t == STATS_TIMEOUT for t in timeouts)
