import asyncio
from types import SimpleNamespace

import aiohttp
import discord
from discord.ext import commands

from gentlebot.cogs import bigdumper_watcher_cog


def test_post_on_new_hr(monkeypatch):
    async def run_test():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = bigdumper_watcher_cog.BigDumperWatcherCog(bot)
        cog.last_hr = 1

        # Patch fetch to return higher HR
        async def fake_fetch_hr():
            return 2
        monkeypatch.setattr(cog, "_fetch_hr", fake_fetch_hr)

        dummy_embed = discord.Embed(title="Big")
        async def fake_embed():
            return dummy_embed
        sports = SimpleNamespace(build_bigdumper_embed=fake_embed)
        monkeypatch.setattr(bigdumper_watcher_cog, "SportsCog", SimpleNamespace)
        monkeypatch.setattr(bot, "get_cog", lambda name: sports if name == "SportsCog" else None)

        sent = []
        class DummyChannel(SimpleNamespace):
            async def send(self, *, embed=None):
                sent.append(embed)
        channel = DummyChannel()
        monkeypatch.setattr(bot, "get_channel", lambda cid: channel)
        monkeypatch.setattr(discord, "TextChannel", DummyChannel)
        async def dummy_wait():
            return None
        monkeypatch.setattr(bot, "wait_until_ready", dummy_wait)

        await bigdumper_watcher_cog.BigDumperWatcherCog.check_task.coro(cog)
        assert sent and sent[0] is dummy_embed
        await cog.session.close()

    asyncio.run(run_test())
def test_fetch_hr_retries(monkeypatch):
    async def run_test():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = bigdumper_watcher_cog.BigDumperWatcherCog(bot)
        calls = {"n": 0}

        class DummyResp:
            def __init__(self):
                self._data = {"stats": [{"splits": [{"stat": {"homeRuns": 7}}]}]}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                pass

            def raise_for_status(self):
                pass

            async def json(self):
                return self._data

        def fake_get(url, params=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise aiohttp.ClientError("boom")
            return DummyResp()

        monkeypatch.setattr(cog.session, "get", fake_get)
        hr = await cog._fetch_hr()
        assert hr == 7
        assert calls["n"] >= 2
        await cog.session.close()

    asyncio.run(run_test())
