import asyncio
from types import SimpleNamespace
from datetime import datetime

import discord
from discord.ext import commands
import asyncpg

from gentlebot.cogs import mariners_game_cog
from gentlebot import db


SUMMARY = {
    "game_pk": 123,
    "mariners_home": False,
    "away_abbr": "SEA",
    "home_abbr": "HOU",
    "mariners_score": 5,
    "opp_score": 3,
    "opp_name": "Astros",
    "opp_abbr": "HOU",
    "start_pst": mariners_game_cog.PST_TZ.localize(datetime(2024, 9, 17, 13, 10)),
    "highlights": [
        "Rodríguez 2-run HR (7th)",
        "Crawford 2B",
        "Muñoz nails down the save.",
    ],
    "record": "82–66 (W2)",
    "al_west": "2nd • 1.5 GB of HOU • Last 10: 7–3",
    "top_performers": {
        "SEA": "Julio Rodríguez: 2-4, HR (28), 2 RBI | George Kirby: 7.0 IP, 6 K, 1 ER",
        "HOU": "Yordan Álvarez: 1-3, HR (34), 2 RBI | Framber Valdez: 6.0 IP, 2 ER, 7 K",
    },
}


def test_build_message():
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    cog = mariners_game_cog.MarinersGameCog(bot)
    msg = cog.build_message(SUMMARY)
    lines = msg.splitlines()
    assert lines[0] == "⚾️ **SEA @ HOU — Tue Sep 17, 1:10 PM PT**"
    assert lines[1] == "*Final*: Mariners 5 — Astros 3"
    assert (
        lines[2]
        == "*Highlights*: Rodríguez 2-run HR (7th); Crawford 2B; Muñoz nails down the save."
    )
    assert lines[3] == "*Record*: 82–66 (W2)"
    assert lines[4] == "*AL West*: 2nd • 1.5 GB of HOU • Last 10: 7–3"
    assert lines[6] == "*Top Performers*"


def test_posts_summary(monkeypatch):
    async def run_test():
        pool = DummyPool()

        async def fake_create_pool(url, *args, **kwargs):
            assert url.startswith("postgresql://")
            return pool

        monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)
        db._pool = None
        monkeypatch.setenv("PG_DSN", "postgresql+asyncpg://u:p@localhost/db")

        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = mariners_game_cog.MarinersGameCog(bot)
        monkeypatch.setattr(cog.game_task, "start", lambda: None)
        await cog.cog_load()
        monkeypatch.setattr(cog, "fetch_game_summary", lambda: SUMMARY)

        sent = []

        class DummyChannel(SimpleNamespace):
            async def send(self, content):
                sent.append(content)

        monkeypatch.setattr(bot, "get_channel", lambda cid: DummyChannel())
        monkeypatch.setattr(discord, "TextChannel", DummyChannel)

        async def dummy_wait():
            return None

        monkeypatch.setattr(bot, "wait_until_ready", dummy_wait)

        await mariners_game_cog.MarinersGameCog.game_task.coro(cog)
        assert sent
        assert "Mariners 5 — Astros 3" in sent[0]

    asyncio.run(run_test())


def test_no_repeat_across_sessions(monkeypatch):
    async def run_test():
        pool = DummyPool()

        async def fake_create_pool(url, *args, **kwargs):
            return pool

        monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)
        db._pool = None
        monkeypatch.setenv("PG_DSN", "postgresql+asyncpg://u:p@localhost/db")

        intents = discord.Intents.none()

        # First session posts the summary and stores game_pk in DB
        bot1 = commands.Bot(command_prefix="!", intents=intents)
        cog1 = mariners_game_cog.MarinersGameCog(bot1)
        monkeypatch.setattr(cog1.game_task, "start", lambda: None)
        await cog1.cog_load()
        monkeypatch.setattr(cog1, "fetch_game_summary", lambda: SUMMARY)
        sent1 = []

        class DummyChannel(SimpleNamespace):
            async def send(self, content):
                sent1.append(content)

        monkeypatch.setattr(bot1, "get_channel", lambda cid: DummyChannel())
        monkeypatch.setattr(discord, "TextChannel", DummyChannel)

        async def dummy_wait():
            return None

        monkeypatch.setattr(bot1, "wait_until_ready", dummy_wait)
        await mariners_game_cog.MarinersGameCog.game_task.coro(cog1)
        assert sent1

        # Second session should read DB and skip reposting
        bot2 = commands.Bot(command_prefix="!", intents=intents)
        cog2 = mariners_game_cog.MarinersGameCog(bot2)
        monkeypatch.setattr(cog2.game_task, "start", lambda: None)
        await cog2.cog_load()
        monkeypatch.setattr(cog2, "fetch_game_summary", lambda: SUMMARY)
        sent2 = []
        monkeypatch.setattr(bot2, "get_channel", lambda cid: DummyChannel())
        monkeypatch.setattr(discord, "TextChannel", DummyChannel)
        monkeypatch.setattr(bot2, "wait_until_ready", dummy_wait)
        await mariners_game_cog.MarinersGameCog.game_task.coro(cog2)
        assert not sent2

    asyncio.run(run_test())


def test_cog_load_starts_without_db(monkeypatch):
    async def run_test():
        async def raise_error():
            raise asyncpg.PostgresError("boom")

        monkeypatch.setattr(mariners_game_cog, "get_pool", raise_error)

        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = mariners_game_cog.MarinersGameCog(bot)

        started = False

        def fake_start():
            nonlocal started
            started = True

        monkeypatch.setattr(cog.game_task, "start", fake_start)
        await cog.cog_load()

        assert started
        assert cog.pool is None

    asyncio.run(run_test())


class DummyPool:
    def __init__(self):
        self.data = set()

    async def close(self):
        pass

    async def fetch(self, query, *args):
        return [(pk,) for pk in self.data]

    async def execute(self, query, *args):
        if "INSERT" in query:
            self.data.add(args[0])
        return ""
