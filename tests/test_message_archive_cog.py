import asyncio
import os

import discord
from discord.ext import commands
import asyncpg

from gentlebot import db
from gentlebot.cogs.message_archive_cog import MessageArchiveCog
from gentlebot.util import build_db_url, ReactionAction


class DummyPool:
    def __init__(self):
        self.executed = []

    async def close(self):
        pass

    async def execute(self, query, *args):
        self.executed.append(query)

    async def fetchval(self, query, *args):
        self.executed.append(query)
        return True


def fake_create_pool(url, *args, **kwargs):
    assert url.startswith("postgresql://")
    return DummyPool()


def test_build_db_url_env(monkeypatch):
    monkeypatch.delenv("PG_DSN", raising=False)
    monkeypatch.setenv("PG_USER", "u")
    monkeypatch.setenv("PG_PASSWORD", "p")
    monkeypatch.setenv("PG_DB", "db")
    assert build_db_url() == "postgresql+asyncpg://u:p@db:5432/db"


def test_build_db_url_database_url(monkeypatch):
    monkeypatch.delenv("PG_DSN", raising=False)
    monkeypatch.delenv("PG_USER", raising=False)
    monkeypatch.delenv("PG_PASSWORD", raising=False)
    monkeypatch.delenv("PG_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/db")
    assert build_db_url() == "postgresql+asyncpg://u:p@db:5432/db"


def test_on_message(monkeypatch):
    async def run_test():
        pool = DummyPool()
        async def fake_create_pool(url, *args, **kwargs):
            assert url.startswith("postgresql://")
            return pool
        monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)
        db._pool = None
        monkeypatch.setenv("ARCHIVE_MESSAGES", "1")
        monkeypatch.setenv("PG_DSN", "postgresql+asyncpg://u:p@localhost/db")
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
            flags=discord.MessageFlags._from_value(0),
            mention_everyone=False,
            raw_mentions=[],
            raw_role_mentions=[],
            embeds=[],
            attachments=[],
            reference=None,
            to_json=lambda: "{}",
        )
        await cog.on_message(message)
        assert pool.executed

    asyncio.run(run_test())


def test_log_reaction_on_conflict(monkeypatch):
    async def run_test():
        pool = DummyPool()
        intents = discord.Intents.default()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = MessageArchiveCog(bot)
        cog.pool = pool

        class Dummy:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        payload = Dummy(message_id=1, user_id=2, emoji="😀")
        await cog._log_reaction(payload, ReactionAction.MESSAGE_REACTION_ADD)
        await cog._log_reaction(payload, ReactionAction.MESSAGE_REACTION_ADD)
        assert any("ON CONFLICT ON CONSTRAINT uniq_reaction_event_msg_user_emoji_act_ts" in q for q in pool.executed)

    asyncio.run(run_test())


def test_insert_message_updates_channel(monkeypatch):
    async def run_test():
        pool = DummyPool()
        intents = discord.Intents.default()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = MessageArchiveCog(bot)
        cog.pool = pool

        executed = []

        async def fake_execute(query, *args):
            executed.append(query)
            return "INSERT 0 1"

        pool.execute = fake_execute

        class Dummy:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        guild = Dummy(id=1, name="g", owner=Dummy(id=2), created_at=None)
        channel = Dummy(id=10, guild=guild, name="c", type=discord.ChannelType.text, created_at=None)
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
            flags=discord.MessageFlags._from_value(0),
            mention_everyone=False,
            raw_mentions=[],
            raw_role_mentions=[],
            embeds=[],
            attachments=[],
            reference=None,
            to_json=lambda: "{}",
        )

        await cog._insert_message(message)
        assert any("UPDATE discord.channel SET last_message_id" in q for q in executed)

    asyncio.run(run_test())

def test_on_ready_populates(monkeypatch):
    async def run_test():
        pool = DummyPool()

        async def fake_create_pool(url, *args, **kwargs):
            return pool

        monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)
        db._pool = None
        monkeypatch.setenv("ARCHIVE_MESSAGES", "1")
        monkeypatch.setenv("PG_DSN", "postgresql+asyncpg://u:p@localhost/db")

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
            global_name="User Global",
            banner=None,
            accent_color=None,
            avatar_decoration=None,
            system=False,
            public_flags=None,
        )
        await cog._upsert_user(member)
        assert pool.executed
        assert "global_name" in pool.executed[0]

    asyncio.run(run_test())


def test_upsert_user_flags(monkeypatch):
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
            global_name="User Global",
            banner=None,
            accent_color=None,
            avatar_decoration=None,
            system=False,
            public_flags=discord.PublicUserFlags._from_value(8),
        )
        await cog._upsert_user(member)
        assert pool.executed

    asyncio.run(run_test())


def test_reply_to_missing(monkeypatch):
    async def run_test():
        pool = DummyPool()

        async def fake_create_pool(url, *args, **kwargs):
            return pool

        monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)
        db._pool = None
        monkeypatch.setenv("ARCHIVE_MESSAGES", "1")
        monkeypatch.setenv("PG_DSN", "postgresql+asyncpg://u:p@localhost/db")

        intents = discord.Intents.default()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = MessageArchiveCog(bot)
        await cog.cog_load()

        async def fake_fetchval(query, *args):
            return None

        pool.fetchval = fake_fetchval

        captured = {}

        async def fake_execute(query, *args):
            if "INSERT INTO discord.message" in query:
                captured["reply"] = args[4]
            pool.executed.append(query)

        pool.execute = fake_execute

        class Dummy:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        guild = Dummy(id=1, name="g", owner=Dummy(id=2), created_at=None)
        channel = Dummy(id=10, guild=guild, name="c", type=discord.ChannelType.text, created_at=None)
        author = Dummy(id=4, name="a", discriminator="1234", avatar=None, bot=False)
        reference = Dummy(message_id=42)
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
            type=discord.MessageType.reply,
            flags=discord.MessageFlags._from_value(0),
            mention_everyone=False,
            raw_mentions=[],
            raw_role_mentions=[],
            embeds=[],
            attachments=[],
            reference=reference,
            to_json=lambda: "{}",
        )
        await cog.on_message(message)
        assert captured.get("reply") is None

    asyncio.run(run_test())
