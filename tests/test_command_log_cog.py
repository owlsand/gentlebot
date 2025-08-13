import asyncio
import json

import discord
from discord.ext import commands
import asyncpg

from gentlebot import db
from gentlebot.cogs.command_log_cog import CommandLogCog


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


def test_command_logged(monkeypatch):
    async def run_test():
        monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)
        db._pool = None
        monkeypatch.setenv("LOG_COMMANDS", "1")
        monkeypatch.setenv("PG_DSN", "postgresql+asyncpg://u:p@localhost/db")

        intents = discord.Intents.default()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = CommandLogCog(bot)
        await cog.cog_load()
        pool = cog.pool

        class DummyInteraction:
            guild_id = 1
            channel_id = 2
            user = type("U", (), {"id": 3})()
            data = {"options": ["foo"]}

        cmd = type("Cmd", (), {"name": "test"})()
        await cog.on_app_command_completion(DummyInteraction(), cmd)

        assert pool.executed

    asyncio.run(run_test())

