import asyncio
from types import SimpleNamespace

import discord
from discord.ext import commands
from discord import app_commands

from gentlebot.cogs import sports_cog
from gentlebot import big_dumper_espn


sample_data = {
    "season_strip": {"HR": "10", "RBI": "30", "OPS": ".800", "SLG": ".500", "AVG": ".250"},
    "recent": {
        "l7": {"slash": "0.200/0.300/0.400", "hr": "1"},
        "l15": {"slash": "0.250/0.320/0.450", "hr": "2"},
        "post": {"slash": "0.260/0.350/0.500", "hr": "5"},
    },
    "pace": 30,
    "latest_hr": {"num": "10", "date": "Jun 10", "opp": "LAA", "ft": "420", "ev": "110", "url": "http://video"},
    "last3_hrs": [("line1", "url1"), ("line2", "url2")],
    "standings": {"rank": "1", "gb": "0", "streak": "W3", "last10": "7-3", "overall": "40-30", "leader": "SEA"},
}


class DummyResponse:
    def __init__(self):
        self.deferred = False

    async def defer(self, *, thinking=True):
        self.deferred = True


class DummyFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class DummyInteraction:
    def __init__(self):
        self.response = DummyResponse()
        self.followup = DummyFollowup()
        self.user = SimpleNamespace(id=1)
        self.channel = SimpleNamespace(id=1, name="chan")


def test_bigdumper_compact(monkeypatch):
    async def fake_gather(*args, **kwargs):
        return sample_data

    monkeypatch.setattr(big_dumper_espn, "gather_big_dumper_data", fake_gather)

    async def inner():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        await bot.load_extension("gentlebot.cogs.sports_cog")
        cog = bot.get_cog("SportsCog")
        interaction = DummyInteraction()
        choice = app_commands.Choice(name="Compact", value="compact")
        await sports_cog.SportsCog.bigdumper.callback(cog, interaction, style=choice)
        assert interaction.followup.sent[0][0].startswith("```")
        await bot.close()

    asyncio.run(inner())


def test_bigdumper_full_default(monkeypatch):
    async def fake_gather(*args, **kwargs):
        return sample_data

    monkeypatch.setattr(big_dumper_espn, "gather_big_dumper_data", fake_gather)

    async def inner():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        await bot.load_extension("gentlebot.cogs.sports_cog")
        cog = bot.get_cog("SportsCog")
        interaction = DummyInteraction()
        await sports_cog.SportsCog.bigdumper.callback(cog, interaction, style=None)
        content, kwargs = interaction.followup.sent[0]
        assert content is None
        embed = kwargs.get("embed")
        assert isinstance(embed, discord.Embed)
        assert embed.title.startswith("Big Dumper — Season Snapshot")
        await bot.close()

    asyncio.run(inner())
