import asyncio
from types import SimpleNamespace
from datetime import datetime

import discord
from discord.ext import commands
import asyncpg
import pytz

from gentlebot.cogs import mariners_game_cog
from gentlebot import db


SUMMARY = {
    "event_id": "401999999",
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

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)
        monkeypatch.setattr(mariners_game_cog.MarinersGameCog, "_ensure_table", noop)
        monkeypatch.setattr(
            mariners_game_cog.MarinersGameCog, "_ensure_tracking_state", noop
        )
        monkeypatch.setattr(mariners_game_cog.MarinersGameCog, "_sync_schedule", noop)
        db._pool = None
        monkeypatch.setenv("PG_DSN", "postgresql+asyncpg://u:p@localhost/db")

        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = mariners_game_cog.MarinersGameCog(bot)
        monkeypatch.setattr(cog.game_task, "start", lambda: None)
        await cog.cog_load()
        cog.tracking_since = pytz.utc.localize(datetime(2024, 1, 1))
        pool.add_summary_row(SUMMARY)

        sent = []

        class DummyChannel(SimpleNamespace):
            async def send(self, content):
                sent.append(content)
                return SimpleNamespace(id=987654321)

        monkeypatch.setattr(bot, "get_channel", lambda cid: DummyChannel())
        monkeypatch.setattr(discord, "TextChannel", DummyChannel)

        async def dummy_wait():
            return None

        monkeypatch.setattr(bot, "wait_until_ready", dummy_wait)

        await mariners_game_cog.MarinersGameCog.game_task.coro(cog)
        assert sent
        assert "Mariners 5 — Astros 3" in sent[0]
        assert pool.rows[SUMMARY["event_id"]]["message_id"] == 987654321

    asyncio.run(run_test())


def test_no_repeat_across_sessions(monkeypatch):
    async def run_test():
        pool = DummyPool()

        async def fake_create_pool(url, *args, **kwargs):
            return pool

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)
        monkeypatch.setattr(mariners_game_cog.MarinersGameCog, "_ensure_table", noop)
        monkeypatch.setattr(
            mariners_game_cog.MarinersGameCog, "_ensure_tracking_state", noop
        )
        monkeypatch.setattr(mariners_game_cog.MarinersGameCog, "_sync_schedule", noop)
        db._pool = None
        monkeypatch.setenv("PG_DSN", "postgresql+asyncpg://u:p@localhost/db")

        intents = discord.Intents.none()

        # First session posts the summary and stores game_pk in DB
        bot1 = commands.Bot(command_prefix="!", intents=intents)
        cog1 = mariners_game_cog.MarinersGameCog(bot1)
        monkeypatch.setattr(cog1.game_task, "start", lambda: None)
        await cog1.cog_load()
        cog1.tracking_since = pytz.utc.localize(datetime(2024, 1, 1))
        pool.add_summary_row(SUMMARY)
        sent1 = []

        class DummyChannel(SimpleNamespace):
            async def send(self, content):
                sent1.append(content)
                return SimpleNamespace(id=111)

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
        cog2.tracking_since = pytz.utc.localize(datetime(2024, 1, 1))
        sent2 = []
        monkeypatch.setattr(bot2, "get_channel", lambda cid: DummyChannel())
        monkeypatch.setattr(discord, "TextChannel", DummyChannel)
        monkeypatch.setattr(bot2, "wait_until_ready", dummy_wait)
        await mariners_game_cog.MarinersGameCog.game_task.coro(cog2)
        assert not sent2

    asyncio.run(run_test())


def test_fetch_game_summary_respects_tracking_since(monkeypatch):
    async def run_test():
        pool = DummyPool()
        pool.add_summary_row(SUMMARY)

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(mariners_game_cog.MarinersGameCog, "_sync_schedule", noop)

        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = mariners_game_cog.MarinersGameCog(bot)
        cog.pool = pool
        cog.tracking_since = pytz.utc.localize(datetime(2025, 1, 1))

        result = await cog.fetch_game_summary()
        assert result is None

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
        self.rows: dict[str, dict] = {}

    async def close(self):
        pass

    async def fetch(self, query, *args):
        if "mariners_schedule" in query and "message_id IS NOT NULL" in query:
            return [
                (event_id,)
                for event_id, row in self.rows.items()
                if row.get("message_id") is not None
            ]
        return []

    async def fetchrow(self, query, *args):
        if "FROM mariners_schedule" in query and "state = 'post'" in query:
            anchor = args[0] if args else None
            candidates = [
                row
                for row in self.rows.values()
                if row.get("state") == "post" and row.get("message_id") is None
                and (anchor is None or row.get("game_date") >= anchor)
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda r: r["game_date"])
            row = candidates[-1]
            return {
                "event_id": row["event_id"],
                "summary": row.get("summary"),
                "mariners_score": row.get("mariners_score"),
                "opponent_score": row.get("opponent_score"),
                "home_away": row.get("home_away"),
                "opponent_abbr": row.get("opponent_abbr"),
                "opponent_name": row.get("opponent_name"),
                "game_date": row.get("game_date"),
                "season_year": row.get("season_year"),
                "short_name": row.get("short_name"),
            }
        return None

    async def execute(self, query, *args):
        if "INSERT INTO mariners_schedule" in query:
            event_id = args[0]
            row = self.rows.get(event_id, {}).copy()
            row.update(
                event_id=event_id,
                season_year=args[1],
                game_date=args[2],
                home_away=args[3],
                opponent_abbr=args[4],
                opponent_name=args[5],
                venue=args[6],
                short_name=args[7],
                state=args[8],
                mariners_score=args[9],
                opponent_score=args[10],
            )
            row.setdefault("summary", None)
            row.setdefault("message_id", None)
            self.rows[event_id] = row
        elif "SET summary" in query:
            summary, mariners_score, opp_score, event_id = args
            row = self.rows[event_id]
            row["summary"] = summary
            row["mariners_score"] = mariners_score
            row["opponent_score"] = opp_score
        elif "SET message_id" in query:
            message_id, event_id = args
            row = self.rows[event_id]
            row["message_id"] = message_id
        return ""

    def add_summary_row(self, summary: dict) -> None:
        stored = dict(summary)
        stored["start_pst"] = stored["start_pst"].isoformat()
        self.rows[summary["event_id"]] = {
            "event_id": summary["event_id"],
            "season_year": summary["start_pst"].year,
            "game_date": summary["start_pst"],
            "home_away": "home" if summary.get("mariners_home") else "away",
            "opponent_abbr": summary["opp_abbr"],
            "opponent_name": summary["opp_name"],
            "venue": "",
            "short_name": f"{summary['away_abbr']} @ {summary['home_abbr']}",
            "state": "post",
            "mariners_score": summary["mariners_score"],
            "opponent_score": summary["opp_score"],
            "summary": stored,
            "message_id": None,
        }
