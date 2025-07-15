import asyncio
from types import SimpleNamespace

import discord
from discord.ext import commands

import bot_config as cfg
from cogs import roles_cog


def test_lurker_skip_if_many_messages(monkeypatch):
    async def run_test():
        monkeypatch.setattr(roles_cog.RoleCog.badge_task, "start", lambda self: None)
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = roles_cog.RoleCog(bot)

        guild = SimpleNamespace(id=1)
        guild.members = [
            SimpleNamespace(id=1, bot=False, roles=[]),
            SimpleNamespace(id=2, bot=False, roles=[]),
        ]
        guild.get_role = lambda rid: SimpleNamespace(id=rid, name=str(rid))
        monkeypatch.setattr(bot, "get_guild", lambda gid: guild)
        monkeypatch.setattr(bot, "wait_until_ready", lambda: asyncio.sleep(0))

        async def fake_rotate_single(*args, **kwargs):
            return None

        monkeypatch.setattr(cog, "_rotate_single", fake_rotate_single)

        assigned = {}

        async def fake_assign_flag(g, member, role_id):
            assigned[member.id] = role_id

        monkeypatch.setattr(cog, "_assign_flag", fake_assign_flag)
        monkeypatch.setattr(roles_cog, "ROLE_LURKER_FLAG", 1)
        monkeypatch.setattr(cfg, "ROLE_LURKER_FLAG", 1)
        now = discord.utils.utcnow()
        cog.messages = [
            {"author": 1, "ts": now, "id": i, "len": 10, "words": 2, "rich": False, "mentions": 0, "mention_ids": [], "reply_to": None}
            for i in range(6)
        ]
        cog.messages += [
            {"author": 2, "ts": now, "id": 100 + i, "len": 10, "words": 2, "rich": False, "mentions": 0, "mention_ids": [], "reply_to": None}
            for i in range(2)
        ]
        cog.reactions = [
            {"ts": now, "msg": 200 + i, "msg_author": 99, "emoji": "👍", "creator": None, "user": 1}
            for i in range(10)
        ]
        cog.last_online = {1: now, 2: now}
        await cog.badge_task()
        assert assigned[1] != roles_cog.ROLE_LURKER_FLAG
        assert assigned[2] == roles_cog.ROLE_LURKER_FLAG

    asyncio.run(run_test())
