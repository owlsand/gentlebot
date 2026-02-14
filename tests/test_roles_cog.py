import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace

import discord
from discord.ext import commands

from gentlebot import bot_config as cfg
from gentlebot.cogs import roles_cog


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
        async def fake_sync_role(*a, **k):
            return None
        monkeypatch.setattr(cog, "_sync_role", fake_sync_role)

        assigned = {}

        async def fake_assign_flag(g, member, role_id):
            assigned[member.id] = role_id

        monkeypatch.setattr(cog, "_assign_flag", fake_assign_flag)
        monkeypatch.setattr(roles_cog, "ROLE_LURKER_FLAG", 1)
        monkeypatch.setattr(cfg, "ROLE_LURKER_FLAG", 1)
        monkeypatch.setattr(cfg, "TIERED_BADGES", {
            'top_poster': {'threshold': 1, 'roles': {'gold': 0, 'silver': 0, 'bronze': 0}},
            'reaction_magnet': {'threshold': 1, 'roles': {'gold': 0, 'silver': 0, 'bronze': 0}},
        }, raising=False)
        now = discord.utils.utcnow()
        cog.messages = [
            {"author": 1, "ts": now, "id": i, "len": 10, "words": 2, "rich": False, "mentions": 0, "mention_ids": [], "reply_to": None}
            for i in range(6)
        ]
        cog.reactions = [
            {"ts": now, "msg": 200 + i, "msg_author": 99, "emoji": "👍", "creator": None, "user": 1}
            for i in range(10)
        ]
        cog.last_online = {1: now, 2: now}
        cog.last_presence = {1: now, 2: now}
        await cog.badge_task()
        assert assigned[1] == 0
        assert assigned[2] == roles_cog.ROLE_LURKER_FLAG

    asyncio.run(run_test())


def test_assign_skips_bot_member(monkeypatch):
    async def run_test():
        monkeypatch.setattr(roles_cog.RoleCog.badge_task, "start", lambda self: None)
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = roles_cog.RoleCog(bot)

        role_id = 42
        role = SimpleNamespace(id=role_id, name="test")

        guild = SimpleNamespace(id=1)
        guild.get_role = lambda rid: role if rid == role_id else None

        member = SimpleNamespace(id=99, guild=guild, roles=[], bot=True)
        added: list[int] = []

        async def fake_add_roles(r, reason=None):
            added.append(r.id)

        member.add_roles = fake_add_roles

        await cog._assign(member, role_id)

        assert added == []

    asyncio.run(run_test())


def test_npc_assigned_if_no_other_flag(monkeypatch):
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
        async def fake_sync_role(*a, **k):
            return None
        monkeypatch.setattr(cog, "_sync_role", fake_sync_role)

        assigned = {}

        async def fake_assign_flag(g, member, role_id):
            assigned[member.id] = role_id

        monkeypatch.setattr(cog, "_assign_flag", fake_assign_flag)
        monkeypatch.setattr(roles_cog, "ROLE_GHOST", 10)
        monkeypatch.setattr(cfg, "ROLE_GHOST", 10)
        monkeypatch.setattr(roles_cog, "ROLE_NPC_FLAG", 20)
        monkeypatch.setattr(cfg, "ROLE_NPC_FLAG", 20)
        monkeypatch.setattr(cfg, "TIERED_BADGES", {
            'top_poster': {'threshold': 1, 'roles': {'gold': 0, 'silver': 0, 'bronze': 0}},
            'reaction_magnet': {'threshold': 1, 'roles': {'gold': 0, 'silver': 0, 'bronze': 0}},
        }, raising=False)

        now = discord.utils.utcnow()
        cog.messages = [
            {"author": 2, "ts": now, "id": i, "len": 10, "words": 2, "rich": False, "mentions": 0, "mention_ids": [], "reply_to": None}
            for i in range(3)
        ]
        cog.reactions = []
        cog.last_online = {1: now, 2: now}
        cog.last_presence = {1: now - timedelta(days=8), 2: now}
        await cog.badge_task()
        assert assigned[1] == roles_cog.ROLE_GHOST
        assert assigned[2] == roles_cog.ROLE_NPC_FLAG

    asyncio.run(run_test())


def test_npc_removed_when_assigning_other_role(monkeypatch):
    async def run_test():
        monkeypatch.setattr(roles_cog.RoleCog.badge_task, "start", lambda self: None)
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = roles_cog.RoleCog(bot)

        npc_id = 20
        other_id = 30

        npc_role = SimpleNamespace(id=npc_id, name="npc")
        other_role = SimpleNamespace(id=other_id, name="other")

        guild = SimpleNamespace(id=1)
        guild.get_role = lambda rid: npc_role if rid == npc_id else other_role if rid == other_id else None

        member = SimpleNamespace(id=1, guild=guild, roles=[npc_role], bot=False)

        removed = []
        added = []

        async def fake_remove(m, rid):
            removed.append(rid)

        async def fake_add_roles(role, reason=None):
            added.append(role.id)

        monkeypatch.setattr(cog, "_remove", fake_remove)
        member.add_roles = fake_add_roles
        monkeypatch.setattr(roles_cog, "ROLE_NPC_FLAG", npc_id)
        monkeypatch.setattr(cfg, "ROLE_NPC_FLAG", npc_id)

        await cog._assign(member, other_id)

        assert npc_id in removed
        assert other_id in added

    asyncio.run(run_test())


def test_presence_archive_prevents_false_ghost(monkeypatch):
    async def run_test():
        monkeypatch.setattr(roles_cog.RoleCog.badge_task, "start", lambda self: None)
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = roles_cog.RoleCog(bot)

        now = discord.utils.utcnow()
        fetch_calls: list[tuple[str, int]] = []

        class FakePool:
            async def fetch(self, query, guild_id, cutoff):
                fetch_calls.append((query.strip().split()[0], guild_id))
                return [{"user_id": 1, "last_event": now}]

        async def fake_get_pool():
            return FakePool()

        monkeypatch.setattr(roles_cog, "get_pool", fake_get_pool)

        guild = SimpleNamespace(id=1)
        guild.members = [
            SimpleNamespace(id=1, bot=False, roles=[], guild=guild),
            SimpleNamespace(id=2, bot=False, roles=[], guild=guild),
        ]
        guild.get_role = lambda rid: SimpleNamespace(id=rid, name=str(rid), members=[])
        guild.get_member = lambda uid: next((m for m in guild.members if m.id == uid), None)
        monkeypatch.setattr(bot, "get_guild", lambda gid: guild)
        monkeypatch.setattr(bot, "wait_until_ready", lambda: asyncio.sleep(0))

        async def fake_rotate_single(*args, **kwargs):
            return None

        async def fake_sync_role(*args, **kwargs):
            return None

        monkeypatch.setattr(cog, "_rotate_single", fake_rotate_single)
        monkeypatch.setattr(cog, "_sync_role", fake_sync_role)

        assigned: dict[int, int] = {}

        async def fake_assign_flag(g, member, role_id):
            assigned[member.id] = role_id

        monkeypatch.setattr(cog, "_assign_flag", fake_assign_flag)
        monkeypatch.setattr(roles_cog, "ROLE_GHOST", 10)
        monkeypatch.setattr(cfg, "ROLE_GHOST", 10)
        monkeypatch.setattr(roles_cog, "ROLE_LURKER_FLAG", 20)
        monkeypatch.setattr(cfg, "ROLE_LURKER_FLAG", 20)
        monkeypatch.setattr(roles_cog, "ROLE_NPC_FLAG", 30)
        monkeypatch.setattr(cfg, "ROLE_NPC_FLAG", 30)
        monkeypatch.setattr(cfg, "TIERED_BADGES", {
            'top_poster': {'threshold': 1, 'roles': {'gold': 0, 'silver': 0, 'bronze': 0}},
            'reaction_magnet': {'threshold': 1, 'roles': {'gold': 0, 'silver': 0, 'bronze': 0}},
        }, raising=False)

        cog.messages = []
        cog.reactions = []
        cog.last_online = {}
        cog.last_presence = {}

        await cog.badge_task()

        assert fetch_calls, "expected archived presence query"
        assert assigned[1] == roles_cog.ROLE_LURKER_FLAG
        assert assigned[2] == roles_cog.ROLE_GHOST

    asyncio.run(run_test())


def test_tiered_role_refresh(monkeypatch):
    async def run_test():
        monkeypatch.setattr(roles_cog.RoleCog.badge_task, "start", lambda self: None)
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = roles_cog.RoleCog(bot)

        guild = SimpleNamespace(id=1)
        role_ids = [10, 20, 30, 40, 50, 60]
        roles = {rid: SimpleNamespace(id=rid, name=str(rid), members=[]) for rid in role_ids}
        guild.get_role = lambda rid: roles.get(rid)
        members = [SimpleNamespace(id=i, bot=False, roles=[], guild=guild) for i in range(1, 10)]
        guild.members = members

        def get_member(uid):
            return next((m for m in members if m.id == uid), None)

        guild.get_member = get_member
        monkeypatch.setattr(bot, "get_guild", lambda gid: guild)
        monkeypatch.setattr(bot, "wait_until_ready", lambda: asyncio.sleep(0))
        async def fake_single(*args, **kwargs):
            return None
        monkeypatch.setattr(cog, "_rotate_single", fake_single)

        calls = {}

        async def fake_sync(g, rid, winners):
            calls[rid] = sorted(winners)

        monkeypatch.setattr(cog, "_sync_role", fake_sync)

        monkeypatch.setattr(cfg, "TIERED_BADGES", {
            'top_poster': {'threshold': 1, 'roles': {'gold': 10, 'silver': 20, 'bronze': 30}},
            'reaction_magnet': {'threshold': 1, 'roles': {'gold': 40, 'silver': 50, 'bronze': 60}},
        }, raising=False)

        now = discord.utils.utcnow()

        def msgs(uid, cnt):
            return [{"author": uid, "ts": now, "id": uid * 100 + i, "len": 0, "words": 0,
                     "rich": False, "mentions": 0, "mention_ids": [], "reply_to": None} for i in range(cnt)]

        cog.messages = []
        counts = [9,8,7,6,5,4,3,2,1]
        for uid, c in enumerate(counts, 1):
            cog.messages += msgs(uid, c)

        def reacts(uid, cnt):
            return [{"ts": now, "msg": uid * 200 + i, "msg_author": uid, "emoji": ":)",
                     "creator": None, "user": 99} for i in range(cnt)]

        cog.reactions = []
        counts_r = [8,7,6,5,4,3,2,1]
        for uid, c in enumerate(counts_r, 1):
            cog.reactions += reacts(uid, c)

        cog.last_online = {m.id: now for m in members}

        await cog.badge_task()

        assert calls[10] == [1]
        assert calls[20] == [2]
        assert calls[30] == [3, 4]
        assert calls[40] == [1]
        assert calls[50] == [2]
        assert calls[60] == [3, 4]

    asyncio.run(run_test())


def test_badge_task_ignores_bot_messages(monkeypatch):
    async def run_test():
        monkeypatch.setattr(roles_cog.RoleCog.badge_task, "start", lambda self: None)
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = roles_cog.RoleCog(bot)

        human = SimpleNamespace(id=1, bot=False, roles=[], guild=None)
        bot_member = SimpleNamespace(id=2, bot=True, roles=[], guild=None)

        guild = SimpleNamespace(id=1)
        guild.members = [human, bot_member]
        guild.get_role = lambda rid: SimpleNamespace(id=rid, name=str(rid))
        monkeypatch.setattr(bot, "get_guild", lambda gid: guild)
        monkeypatch.setattr(bot, "wait_until_ready", lambda: asyncio.sleep(0))

        winner: int | None = None

        async def fake_single(g, rid, uid):
            nonlocal winner
            if rid == roles_cog.ROLE_TOP_POSTER and uid is not None:
                winner = uid

        async def fake_sync(*args, **kwargs):
            return None

        monkeypatch.setattr(cog, "_rotate_single", fake_single)
        monkeypatch.setattr(cog, "_sync_role", fake_sync)
        monkeypatch.setattr(
            cfg,
            "TIERED_BADGES",
            {
                "top_poster": {"threshold": 100, "roles": {}},
                "reaction_magnet": {"threshold": 100, "roles": {}},
            },
            raising=False,
        )
        async def fake_assign_flag(*a, **k):
            return None

        monkeypatch.setattr(cog, "_assign_flag", fake_assign_flag)

        human.guild = guild
        bot_member.guild = guild

        now = discord.utils.utcnow()
        # many bot messages, few human messages
        cog.messages = [
            {"author": bot_member.id, "ts": now, "id": i, "len": 1, "words": 1, "rich": False, "mentions": 0, "mention_ids": [], "reply_to": None}
            for i in range(10)
        ] + [
            {"author": human.id, "ts": now, "id": 100 + i, "len": 1, "words": 1, "rich": False, "mentions": 0, "mention_ids": [], "reply_to": None}
            for i in range(2)
        ]
        cog.reactions = []
        cog.last_online = {human.id: now, bot_member.id: now}

        await cog.badge_task()
        assert winner == human.id

    asyncio.run(run_test())


def test_assign_forbidden_logs_warning(monkeypatch, caplog):
    """discord.Forbidden in _assign should log WARNING, not ERROR."""

    async def run_test():
        monkeypatch.setattr(roles_cog.RoleCog.badge_task, "start", lambda self: None)
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = roles_cog.RoleCog(bot)

        role_id = 42
        role = SimpleNamespace(id=role_id, name="test")

        guild = SimpleNamespace(id=1)
        guild.get_role = lambda rid: role if rid == role_id else None

        member = SimpleNamespace(id=99, guild=guild, roles=[], bot=False)

        async def raise_forbidden(r, reason=None):
            resp = SimpleNamespace(status=403, reason="Forbidden")
            raise discord.Forbidden(resp, "Missing permissions")

        member.add_roles = raise_forbidden
        monkeypatch.setattr(roles_cog, "ROLE_NPC_FLAG", 0)
        monkeypatch.setattr(cfg, "ROLE_NPC_FLAG", 0)

        with caplog.at_level(logging.DEBUG):
            await cog._assign(member, role_id)

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("Missing permissions" in r.message for r in warning_records)
        assert not error_records

    asyncio.run(run_test())


def test_remove_forbidden_logs_warning(monkeypatch, caplog):
    """discord.Forbidden in _remove should log WARNING, not ERROR."""

    async def run_test():
        monkeypatch.setattr(roles_cog.RoleCog.badge_task, "start", lambda self: None)
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = roles_cog.RoleCog(bot)

        role_id = 42
        role = SimpleNamespace(id=role_id, name="test")

        guild = SimpleNamespace(id=1)
        guild.get_role = lambda rid: role if rid == role_id else None

        member = SimpleNamespace(id=99, guild=guild, roles=[role], bot=False)

        async def raise_forbidden(r, reason=None):
            resp = SimpleNamespace(status=403, reason="Forbidden")
            raise discord.Forbidden(resp, "Missing permissions")

        member.remove_roles = raise_forbidden

        with caplog.at_level(logging.DEBUG):
            await cog._remove(member, role_id)

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("Missing permissions" in r.message for r in warning_records)
        assert not error_records

    asyncio.run(run_test())
