from types import SimpleNamespace
import asyncio
import discord
from discord.ext import commands

from datetime import datetime, timezone
from gentlebot.cogs.f1_thread_cog import F1ThreadCog, iso_to_flag


class DummyThread(SimpleNamespace):
    async def delete(self):
        self.deleted = True


def test_open_threads(monkeypatch):
    async def run_test():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = F1ThreadCog(bot)
        monkeypatch.setattr(cog, "_refresh_schedule", lambda: None)
        monkeypatch.setattr(cog, "session_task", SimpleNamespace(start=lambda: None))
        monkeypatch.setattr(bot, "loop", SimpleNamespace(create_task=lambda c: None))
        
        session = {
            "id": 1,
            "country_iso": "HU",
            "year": 2025,
            "gp_name": "Hungarian",
            "session": "QUALI",
            "starts_at": datetime(2025, 7, 26, 14, 0, tzinfo=timezone.utc),
        }

        async def fake_due_sessions():
            return [session]

        monkeypatch.setattr(cog, "_due_sessions", fake_due_sessions)

        created = []

        async def fake_create_thread(name, auto_archive_duration=None):
            t = DummyThread(id=123, name=name, deleted=False, sent=[])
            created.append(name)
            return t

        class DummyChannel(SimpleNamespace):
            create_thread = staticmethod(fake_create_thread)

        sent = []
        DummyThread.send = lambda self, msg: sent.append(msg)
        channel = DummyChannel()
        monkeypatch.setattr(bot, "get_channel", lambda cid: channel)
        monkeypatch.setattr(discord, "TextChannel", DummyChannel)
        marked = []

        async def fake_mark(session_id, thread_id):
            marked.append((session_id, thread_id))

        monkeypatch.setattr(cog, "_mark_started", fake_mark)
        monkeypatch.setattr(cog, "_delete_after", lambda *a, **k: None)
        monkeypatch.setattr(bot.loop, "create_task", lambda coro: None)

        await cog._open_threads()
        flag = iso_to_flag("HU")
        expected_title = f"{flag} 2025 Hungarian GP | Qualifying — Sat 07:00 PDT"
        assert created == [expected_title]
        assert marked == [(1, 123)]
        assert sent[0].startswith(f"**{flag} 2025 Hungarian GP – Qualifying**")

    asyncio.run(run_test())
