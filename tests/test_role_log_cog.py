import discord
from discord.ext import commands
import asyncpg

from gentlebot.cogs.role_log_cog import RoleLogCog
import json


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


def test_role_add_logged(monkeypatch):
    async def run_test():
        monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)
        monkeypatch.setenv("LOG_ROLES", "1")
        monkeypatch.setenv("PG_DSN", "postgresql+asyncpg://u:p@localhost/db")
        intents = discord.Intents.default()
        intents.members = True
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = RoleLogCog(bot)
        await cog.cog_load()
        pool = cog.pool
        class Tags:
            __slots__ = ("bot_id",)

            def __init__(self):
                self.bot_id = 4
        guild = type(
            "G",
            (),
            {
                "id": 1,
                "get_role": lambda self, rid: type(
                    "R",
                    (),
                    {
                        "id": rid,
                        "guild": self,
                        "name": "r",
                        "color": discord.Colour.default(),
                        "tags": Tags(),
                        "permissions": discord.Permissions.none(),
                        "hoist": False,
                        "mentionable": False,
                        "managed": False,
                        "icon": None,
                        "unicode_emoji": None,
                        "flags": discord.RoleFlags(),
                        "position": 0,
                    },
                )(),
            },
        )()
        before = type("M", (), {"id": 10, "guild": guild, "roles": []})()
        after = type("M", (), {"id": 10, "guild": guild, "roles": [guild.get_role(5)]})()
        await cog.on_member_update(before, after)
        assert pool.executed
        role_query, role_args = pool.executed[0]
        assert "INSERT INTO discord.role" in role_query
        assert isinstance(role_args[-1], str)
    import asyncio
    asyncio.run(run_test())
