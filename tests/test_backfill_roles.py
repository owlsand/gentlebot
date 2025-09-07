import asyncio
import discord

from gentlebot.backfill_roles import BackfillBot


class DummyPool:
    def __init__(self):
        self.fetchval_calls = []
        self.execute_calls = []

    async def fetchval(self, query, *args):
        self.fetchval_calls.append((query, args))
        return 1

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        return "INSERT 0 1"

    async def close(self):
        pass


def test_tags_serialized():
    async def run_test():
        bot = BackfillBot()
        bot.pool = DummyPool()
        bot._connection.user = type("U", (), {"id": 1, "name": "u"})()

        class Tags:
            __slots__ = ("bot_id",)

            def __init__(self):
                self.bot_id = 4

        role = type(
            "R",
            (),
            {
                "id": 5,
                "guild": None,
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
        )()
        guild = type("G", (), {"id": 1, "roles": [role], "members": [],})()
        role.guild = guild
        member = type("M", (), {"id": 10, "roles": [role]})()
        guild.members.append(member)
        bot._connection._guilds = {guild.id: guild}

        await bot.on_ready()
        assert bot.pool.fetchval_calls
        query, args = bot.pool.fetchval_calls[0]
        assert isinstance(args[-1], str)

    asyncio.run(run_test())
