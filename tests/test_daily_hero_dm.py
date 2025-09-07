"""Tests for the DailyHeroDMCog message generation."""
import os
import asyncio
import logging
from types import SimpleNamespace

import pytest
import discord
from discord.ext import commands
from apscheduler.triggers.cron import CronTrigger

from gentlebot import bot_config as cfg
from gentlebot.tasks.daily_hero_dm import DailyHeroDMCog
from gentlebot.llm.router import router


@pytest.fixture()
def cog(monkeypatch):
    os.environ.setdefault("GEMINI_API_KEY", "dummy")
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    return DailyHeroDMCog(bot)


def test_generate_message_fallback(cog, monkeypatch):
    monkeypatch.setattr(router, "generate", lambda *a, **k: "Hello there")
    msg = asyncio.run(cog._generate_message("Tester", 5))
    assert "Daily Hero role until midnight Pacific" in msg
    assert "Gentlefolk" in msg
    assert "5th time" in msg


def test_generate_message_success(cog, monkeypatch):
    sample = (
        "Greetings, Tester; your valiant efforts in Gentlefolk yesterday earned the Daily Hero honour for the 5th time, "
        "lasting until midnight, so savour this distinguished laurel."
    )

    monkeypatch.setattr(router, "generate", lambda *a, **k: sample)
    msg = asyncio.run(cog._generate_message("Tester", 5))
    assert msg == sample


def test_generate_message_case_insens(cog, monkeypatch):
    sample = (
        "Salutations, Tester; your efforts in Gentlefolk yesterday earned you the daily hero title for the 5th time."
    )

    monkeypatch.setattr(router, "generate", lambda *a, **k: sample)
    msg = asyncio.run(cog._generate_message("Tester", 5))
    assert msg == sample


def test_send_dm_logged(cog, monkeypatch, caplog):
    async def run_test():
        async def dummy_wait():
            return None

        monkeypatch.setattr(cog.bot, "wait_until_ready", dummy_wait)
        monkeypatch.setattr(cfg, "GUILD_ID", 1, raising=False)
        monkeypatch.setattr(cfg, "ROLE_DAILY_HERO", 2, raising=False)

        sent = []

        class DummyMember(SimpleNamespace):
            display_name = "Tester"
            id = 1

            async def send(self, message):
                sent.append(message)

        member = DummyMember()
        role = SimpleNamespace(id=2, members=[member])
        guild = SimpleNamespace(get_role=lambda _id: role)
        monkeypatch.setattr(cog.bot, "get_guild", lambda _id: guild)

        async def fake_generate(name, wins):
            return f"Hello Hero {wins}"

        async def fake_count(role_id, user_id):
            return 5

        monkeypatch.setattr(cog, "_generate_message", fake_generate)
        monkeypatch.setattr(cog, "_win_count", fake_count)

        caplog.set_level(logging.INFO)
        await cog._send_dm()

        assert sent == ["Hello Hero 5"]
        assert any("Sent Daily Hero DM to Tester: Hello Hero 5" in r.message for r in caplog.records)

    asyncio.run(run_test())


def test_dm_scheduled_after_rotation(cog, monkeypatch):
    captured: dict[str, CronTrigger] = {}

    class DummyScheduler:
        def __init__(self, timezone):
            self.timezone = timezone

        def add_job(self, func, trigger):
            captured["trigger"] = trigger

        def start(self):
            pass

        def shutdown(self, wait=False):
            pass

    import gentlebot.tasks.daily_hero_dm as module

    monkeypatch.setattr(module, "AsyncIOScheduler", DummyScheduler)

    asyncio.run(cog.cog_load())

    trigger = captured.get("trigger")
    assert isinstance(trigger, CronTrigger)
    assert "hour='9'" in str(trigger)
    assert "minute='0'" in str(trigger)
