import asyncio
from types import SimpleNamespace

import discord
from discord.ext import commands
import feedparser

from gentlebot.cogs.techmeme_cog import TechmemeCog


class DummyResponse:
    def __init__(self):
        self.deferred = False
        self.ephemeral = None

    async def defer(self, *, thinking=True, ephemeral=False):
        self.deferred = True
        self.ephemeral = ephemeral


class DummyFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, message, *, ephemeral=False):
        self.sent.append((message, ephemeral))


class DummyInteraction:
    def __init__(self):
        self.user = SimpleNamespace(id=1)
        self.channel = SimpleNamespace(id=1, name="chan")
        self.response = DummyResponse()
        self.followup = DummyFollowup()


def make_feed():
    entries = []
    for i in range(5):
        entries.append(
            feedparser.util.FeedParserDict(
                guid=str(i),
                title=f"<b>Headline {i} (Source)</b>",
                link=f"https://example.com/{i}",
                summary=f"<a href='https://example.com/a{i}'>Article</a> " + "x" * 400,
                published="Thu, 01 Jan 1970 00:00:00 GMT",
            )
        )
    return SimpleNamespace(entries=entries, feed={"lastBuildDate": "now"})


def test_message_split(monkeypatch):
    async def run_test():
        monkeypatch.setattr(feedparser, "parse", lambda url: make_feed())
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = TechmemeCog(bot)
        interaction = DummyInteraction()
        await TechmemeCog.techmeme.callback(cog, interaction, ephemeral=False)
        assert interaction.response.deferred
        assert interaction.followup.sent
        for message, _ in interaction.followup.sent:
            assert len(message) <= 2000
    asyncio.run(run_test())

