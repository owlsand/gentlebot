import asyncio
import asyncpg
import asyncio
import asyncpg
import discord
from discord.ext import commands

from gentlebot.cogs.presence_archive_cog import PresenceArchiveCog


class DummyPool:
    def __init__(self):
        self.executed = []

    async def close(self):
        pass

    async def execute(self, query, *args):
        self.executed.append((query, args))


async def fake_create_pool(url, *args, **kwargs):
    assert url.startswith("postgresql://")
    return DummyPool()


def test_presence_logged(monkeypatch):
    async def run_test():
        monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)
        monkeypatch.setenv("ARCHIVE_PRESENCE", "1")
        monkeypatch.setenv("PG_DSN", "postgresql+asyncpg://u:p@localhost/db")
        intents = discord.Intents.default()
        intents.members = True
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = PresenceArchiveCog(bot)
        await cog.cog_load()
        pool = cog.pool
        class DummyActivity:
            def to_dict(self):
                return {"name": "a"}
        guild = type("G", (), {"id": 1})()
        before = type("M", (), {
            "guild": guild,
            "id": 2,
            "activities": [],
            "raw_status": "offline",
            "desktop_status": discord.Status.offline,
            "mobile_status": discord.Status.offline,
            "web_status": discord.Status.offline,
        })()
        after = type("M", (), {
            "guild": guild,
            "id": 2,
            "activities": [DummyActivity()],
            "raw_status": "online",
            "desktop_status": discord.Status.online,
            "mobile_status": discord.Status.offline,
            "web_status": discord.Status.online,
        })()
        await cog.on_presence_update(before, after)
        assert pool.executed
        query, args = pool.executed[0]
        assert "INSERT INTO discord.presence_update" in query
        assert args[0] == 1
        assert args[1] == 2
    asyncio.run(run_test())
