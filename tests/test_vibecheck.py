import asyncio
import pytest
import discord
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from discord.ext import commands

from gentlebot.cogs import vibecheck_cog
from gentlebot.cogs.vibecheck_cog import (
    z_to_bar,
    VibeCheckCog,
    ArchivedMessage,
)


@pytest.mark.parametrize(
    "z,bar",
    [
        (-3.0, "▁"),
        (-1.5, "▂"),
        (0.0, "▄"),
        (1.0, "▅"),
        (2.6, "▇"),
    ],
)
def test_z_to_bar(z, bar):
    assert z_to_bar(z) == bar


def test_friendship_tips(monkeypatch):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)
    cur = [SimpleNamespace(content="hi", author=SimpleNamespace(display_name="a"))]
    prior = [SimpleNamespace(content="hi", author=SimpleNamespace(display_name="b"))]

    def fake_generate(route, messages, temperature, think_budget=0, json_mode=False):
        return "tip1\ntip2"

    monkeypatch.setattr(vibecheck_cog.router, "generate", fake_generate)

    async def run():
        tips = await cog._friendship_tips(cur, prior)
        await bot.close()
        return tips

    tips = asyncio.run(run())
    assert tips == ["tip1 tip2"]


def test_derive_topics_uses_gemini(monkeypatch):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)
    now = datetime.now(timezone.utc)
    msgs = [
        ArchivedMessage(1, "c", 1, "a", "hello world", now, False, 0),
        ArchivedMessage(1, "c", 2, "b", "more chats", now, False, 0),
    ]

    def fake_generate(route, messages, temperature, think_budget=0, json_mode=False):
        assert route == "general"
        return "topic one\ntopic two"

    monkeypatch.setattr(vibecheck_cog.router, "generate", fake_generate)

    async def run():
        topics = await cog._derive_topics(msgs)
        await bot.close()
        return topics

    topics = asyncio.run(run())
    assert topics == ("topic one", "topic two")


def test_derive_topics_skips_empty(monkeypatch):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)
    now = datetime.now(timezone.utc)
    msgs = [
        ArchivedMessage(1, "c", 1, "a", None, now, False, 0),
    ]

    def boom(*args, **kwargs):
        raise AssertionError("should not call")

    monkeypatch.setattr(vibecheck_cog.router, "generate", boom)

    async def run():
        topics = await cog._derive_topics(msgs)
        await bot.close()
        return topics

    topics = asyncio.run(run())
    assert topics == ("...", "...")


def test_vibecheck_defers(monkeypatch):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)
    cog.pool = object()

    async def fake_gather(start, end):
        return []

    async def fake_tips(cur, prior):
        return ["tip"]

    monkeypatch.setattr(cog, "_gather_messages", fake_gather)
    monkeypatch.setattr(cog, "_friendship_tips", fake_tips)

    class DummyResponse:
        def __init__(self):
            self.deferred = False
            self.kw = None

        async def defer(self, **kwargs):
            self.deferred = True
            self.kw = kwargs

    class DummyFollowup:
        def __init__(self):
            self.sent = None

        async def send(self, content, **kwargs):
            self.sent = (content, kwargs)

    interaction = SimpleNamespace(
        user=SimpleNamespace(display_name="u", id=1),
        channel=SimpleNamespace(name="c"),
        response=DummyResponse(),
        followup=DummyFollowup(),
    )

    async def run():
        await VibeCheckCog.vibecheck.callback(cog, interaction)
        await bot.close()

    asyncio.run(run())

    assert interaction.response.deferred is True
    assert interaction.followup.sent is not None
    assert interaction.followup.sent[1].get("ephemeral") is True


def test_third_place_includes_hero_counts(monkeypatch):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)
    cog.pool = object()

    now = datetime.now(timezone.utc)
    msgs = []
    day1 = now - timedelta(days=1)
    for _ in range(5):
        msgs.append(
            ArchivedMessage(1, "c", 1, "u1", "m", day1, False, 0)
        )
    msgs.append(ArchivedMessage(1, "c", 2, "u2", "m", day1, False, 0))
    msgs.append(ArchivedMessage(1, "c", 3, "u3", "m", day1, False, 0))

    day2 = now - timedelta(days=2)
    for _ in range(4):
        msgs.append(
            ArchivedMessage(1, "c", 2, "u2", "m", day2, False, 0)
        )
    msgs.append(ArchivedMessage(1, "c", 1, "u1", "m", day2, False, 0))
    msgs.append(ArchivedMessage(1, "c", 3, "u3", "m", day2, False, 0))

    day3 = now - timedelta(days=3)
    for _ in range(3):
        msgs.append(
            ArchivedMessage(1, "c", 3, "u3", "m", day3, False, 0)
        )
    msgs.append(ArchivedMessage(1, "c", 1, "u1", "m", day3, False, 0))
    msgs.append(ArchivedMessage(1, "c", 2, "u2", "m", day3, False, 0))

    async def fake_gather(start, end):
        return msgs

    async def fake_tips(cur, prior):
        return []

    monkeypatch.setattr(cog, "_gather_messages", fake_gather)
    monkeypatch.setattr(cog, "_friendship_tips", fake_tips)

    async def fake_topics(msgs):
        return ("t1", "t2")

    monkeypatch.setattr(cog, "_derive_topics", fake_topics)

    class DummyResponse:
        def __init__(self):
            self.deferred = False

        async def defer(self, **kwargs):
            self.deferred = True

    class DummyFollowup:
        def __init__(self):
            self.sent = None

        async def send(self, content, **kwargs):
            self.sent = (content, kwargs)

    interaction = SimpleNamespace(
        user=SimpleNamespace(display_name="u", id=1),
        channel=SimpleNamespace(name="c"),
        response=DummyResponse(),
        followup=DummyFollowup(),
    )

    async def run():
        await VibeCheckCog.vibecheck.callback(cog, interaction)
        await bot.close()

    asyncio.run(run())

    output = interaction.followup.sent[0]
    third_line = next(l for l in output.splitlines() if l.startswith("🥉"))
    assert "Daily Hero" in third_line


def test_gather_messages_uses_reaction_action():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)

    class DummyPool:
        def __init__(self):
            self.queries = []

        async def fetch(self, query, *args):
            self.queries.append(query)
            return []

    pool = DummyPool()
    cog.pool = pool

    async def run():
        now = datetime.now(timezone.utc)
        await cog._gather_messages(now, now)
        await bot.close()

    asyncio.run(run())

    assert pool.queries, "query not executed"
    q = pool.queries[0]
    assert "reaction_action" in q
    assert "action = 0" not in q
    assert "action = 1" not in q

