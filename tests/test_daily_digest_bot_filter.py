import asyncio
from types import SimpleNamespace
import discord
from discord.ext import commands
from gentlebot.tasks import daily_digest


def test_sync_role_skips_bot_member(monkeypatch):
    async def run_test():
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        cog = daily_digest.DailyDigestCog(bot)
        guild = SimpleNamespace(id=1)
        role = SimpleNamespace(id=42, name="hero", members=[])
        guild.get_role = lambda rid: role if rid == 42 else None

        human = SimpleNamespace(id=1, bot=False, roles=[], guild=guild)
        bot_member = SimpleNamespace(id=2, bot=True, roles=[], guild=guild)
        guild.get_member = lambda uid: {1: human, 2: bot_member}.get(uid)

        added = []

        async def add_roles(self, r, reason=None):
            added.append(self.id)
        async def remove_roles(self, r, reason=None):
            pass

        human.add_roles = add_roles.__get__(human, SimpleNamespace)
        bot_member.add_roles = add_roles.__get__(bot_member, SimpleNamespace)
        human.remove_roles = remove_roles.__get__(human, SimpleNamespace)
        bot_member.remove_roles = remove_roles.__get__(bot_member, SimpleNamespace)

        await cog._sync_role(guild, 42, [1, 2])
        assert added == [1]

    asyncio.run(run_test())
