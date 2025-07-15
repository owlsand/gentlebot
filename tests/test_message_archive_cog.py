import asyncio
import os

import discord
from discord.ext import commands
import asyncpg

from gentlebot.cogs.message_archive_cog import MessageArchiveCog


class DummyPool:
    def __init__(self):
        self.executed = []

    async def close(self):
        pass

    async def execute(self, query, *args):
        self.executed.append(query)


def fake_create_pool(url, *args, **kwargs):
    assert url.startswith("postgresql://")
    return DummyPool()


def test_build_db_url_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PG_USER", "u")
    monkeypatch.setenv("PG_PASSWORD", "p")
    monkeypatch.setenv("PG_DB", "db")
    assert MessageArchiveCog._build_db_url() == "postgresql+asyncpg://u:p@db:5432/db"


def test_on_message(monkeypatch):
    async def run_test():
        pool = DummyPool()
        async def fake_create_pool(url, *args, **kwargs):
            assert url.startswith("postgresql://")
            return pool
        monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)
        monkeypatch.setenv("ARCHIVE_MESSAGES", "1")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
        intents = discord.Intents.default()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = MessageArchiveCog(bot)
        await cog.cog_load()

        class Dummy:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        guild = Dummy(id=1, name="g", owner=Dummy(id=2), created_at=None)
        channel = Dummy(id=10, guild=guild, name="chan", type=discord.ChannelType.text, created_at=None)
        author = Dummy(id=4, name="a", discriminator="1234", avatar=None, bot=False)
        message = Dummy(
            id=123,
            guild=guild,
            channel=channel,
            author=author,
            content="hi",
            created_at=discord.utils.utcnow(),
            edited_at=None,
            pinned=False,
            tts=False,
            type=discord.MessageType.default,
            attachments=[],
            reference=None,
            to_json=lambda: "{}",
        )
        await cog.on_message(message)
        assert pool.executed

    asyncio.run(run_test())

def test_on_ready_populates(monkeypatch):
    async def run_test():
        pool = DummyPool()

        async def fake_create_pool(url, *args, **kwargs):
            return pool

        monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)
        monkeypatch.setenv("ARCHIVE_MESSAGES", "1")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

        intents = discord.Intents.default()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = MessageArchiveCog(bot)
        await cog.cog_load()

        class Dummy:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        guild = Dummy(id=1, name="g", owner=Dummy(id=2), created_at=None)
        chan = Dummy(id=10, guild=guild, name="c", type=discord.ChannelType.text, created_at=None)
        guild.channels = [chan]
        monkeypatch.setattr(type(bot), "guilds", property(lambda self: [guild]), raising=False)

        called = []

        async def fake_upsert_guild(g):
            called.append("g")

        async def fake_upsert_channel(c):
            called.append("c")

        monkeypatch.setattr(cog, "_upsert_guild", fake_upsert_guild)
        monkeypatch.setattr(cog, "_upsert_channel", fake_upsert_channel)

        await cog.on_ready()

        assert called == ["g", "c"]

    asyncio.run(run_test())


def test_upsert_user(monkeypatch):
    async def run_test():
        pool = DummyPool()
        intents = discord.Intents.default()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = MessageArchiveCog(bot)
        cog.pool = pool

        class Dummy:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        member = Dummy(
            id=1,
            name="user",
            discriminator="0001",
            avatar=None,
            bot=False,
            display_name="User Display",
        )
        await cog._upsert_user(member)
        assert pool.executed
        assert "display_name" in pool.executed[0]

    asyncio.run(run_test())
