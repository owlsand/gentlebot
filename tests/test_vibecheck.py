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
    assert tips == ["tip1", "tip2"]


def test_derive_topics_handles_none_content():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)
    now = datetime.now(timezone.utc)
    msgs = [
        ArchivedMessage(
            channel_id=1,
            channel_name="c",
            author_id=1,
            author_name="a",
            content=None,
            created_at=now,
            has_image=False,
            reactions=0,
        ),
        ArchivedMessage(
            channel_id=1,
            channel_name="c",
            author_id=2,
            author_name="b",
            content="hello world",
            created_at=now,
            has_image=False,
            reactions=0,
        ),
    ]
    topics = cog._derive_topics(msgs)
    asyncio.run(bot.close())
    assert topics == ["hello world", "..."]


def test_derive_topics_filters_names_and_diff():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)
    now = datetime.now(timezone.utc)
    msgs = [
        ArchivedMessage(
            channel_id=1,
            channel_name="c",
            author_id=1,
            author_name="Alice",
            content="Alice loves pizza and pasta",
            created_at=now,
            has_image=False,
            reactions=0,
        ),
        ArchivedMessage(
            channel_id=1,
            channel_name="c",
            author_id=2,
            author_name="Bob",
            content="Bob loves pizza and chess",
            created_at=now,
            has_image=False,
            reactions=0,
        ),
        ArchivedMessage(
            channel_id=1,
            channel_name="c",
            author_id=3,
            author_name="Eve",
            content="dogs chase cats daily",
            created_at=now,
            has_image=False,
            reactions=0,
        ),
    ]
    topics = cog._derive_topics(msgs)
    asyncio.run(bot.close())
    assert all(
        name not in t.lower() for name in ["alice", "bob"] for t in topics
    )
    assert set(topics[0].split()).isdisjoint(set(topics[1].split()))


def test_vibecheck_defers(monkeypatch):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)
    cog.pool = object()

    async def fake_gather(start, end):
        return []

    async def fake_tips(cur, prior):
        return ["tip"]

    async def fake_public_ids():
        return set()

    monkeypatch.setattr(cog, "_gather_messages", fake_gather)
    monkeypatch.setattr(cog, "_friendship_tips", fake_tips)
    monkeypatch.setattr(cog, "_public_channel_ids", fake_public_ids)
    async def fake_hero_wins(uids):
        return {}
    monkeypatch.setattr(cog, "_daily_hero_wins", fake_hero_wins)

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
    for _ in range(5):
        msgs.append(ArchivedMessage(1, "c", 1, "u1", "m", now, False, 0))
    for _ in range(4):
        msgs.append(ArchivedMessage(1, "c", 2, "u2", "m", now, False, 0))
    for _ in range(3):
        msgs.append(ArchivedMessage(1, "c", 3, "u3", "m", now, False, 0))

    async def fake_gather(start, end):
        return msgs

    async def fake_tips(cur, prior):
        return []

    monkeypatch.setattr(cog, "_gather_messages", fake_gather)
    monkeypatch.setattr(cog, "_friendship_tips", fake_tips)
    monkeypatch.setattr(cog, "_derive_topics", lambda msgs: ("t1", "t2"))
    async def fake_public_ids():
        return {1}
    monkeypatch.setattr(cog, "_public_channel_ids", fake_public_ids)
    async def fake_hero_wins(uids):
        return {1: 5, 2: 2, 3: 1}
    monkeypatch.setattr(cog, "_daily_hero_wins", fake_hero_wins)

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
    lines = output.splitlines()
    first = next(l for l in lines if l.startswith("🥇"))
    second = next(l for l in lines if l.startswith("🥈"))
    third = next(l for l in lines if l.startswith("🥉"))
    assert "5x Daily Hero" in first
    assert "2x Daily Hero" in second
    assert "1x Daily Hero" in third


def test_vibecheck_omits_private_channels(monkeypatch):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)
    cog.pool = object()
    now = datetime.now(timezone.utc)
    msgs = [
        ArchivedMessage(1, "public", 1, "u1", "m", now, False, 0),
        ArchivedMessage(2, "secret", 2, "u2", "m", now, False, 0),
    ]

    async def fake_gather(start, end):
        return msgs

    async def fake_tips(cur, prior):
        return []

    async def fake_public_ids():
        return {1}

    monkeypatch.setattr(cog, "_gather_messages", fake_gather)
    monkeypatch.setattr(cog, "_friendship_tips", fake_tips)
    monkeypatch.setattr(cog, "_derive_topics", lambda m: ("t1", "t2"))
    monkeypatch.setattr(cog, "_public_channel_ids", fake_public_ids)
    async def fake_hero_wins2(uids):
        return {}
    monkeypatch.setattr(cog, "_daily_hero_wins", fake_hero_wins2)

    class DummyResponse:
        async def defer(self, **kwargs):
            pass

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
    assert "#secret" not in output
    assert "#public" in output


def test_gather_messages_filters_private_channels():
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
    q = pool.queries[0].lower()
    assert "reaction_action" in q
    assert "is_private" in q
    assert "action = 0" not in q
    assert "action = 1" not in q


def test_public_channel_ids_query():
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
        await cog._public_channel_ids()
        await bot.close()

    asyncio.run(run())

    assert pool.queries, "query not executed"
    q = pool.queries[0].lower()
    assert "is_private" in q


def test_daily_hero_wins_query():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)

    class DummyPool:
        def __init__(self):
            self.queries: list[str] = []

        async def fetchrow(self, query, *args):
            self.queries.append(query)
            uid = args[1]
            data = {1: 3, 2: 1}
            return {"c": data.get(uid, 0)}

    pool = DummyPool()
    cog.pool = pool

    async def run():
        wins = await cog._daily_hero_wins([1, 2])
        await bot.close()
        return wins

    wins = asyncio.run(run())

    assert len(pool.queries) == 2
    q = pool.queries[0].lower()
    assert "role_event" in q
    assert "action=1" in q.replace(" ", "")
    assert wins == {1: 3, 2: 1}

