import asyncio

from gentlebot.cogs.bigdumper_watcher_cog import BigDumperWatcherCog
from gentlebot.cogs.sports_cog import STATS_TIMEOUT


def test_session_timeout_default():
    async def run_test():
        cog = BigDumperWatcherCog(bot=None)
        assert cog.session.timeout.total == STATS_TIMEOUT
        await cog.session.close()

    asyncio.run(run_test())
