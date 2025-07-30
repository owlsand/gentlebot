import asyncio
from types import SimpleNamespace

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
        monkeypatch.setattr(cog, "_fetch_hr", lambda: 2)

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

    asyncio.run(run_test())
