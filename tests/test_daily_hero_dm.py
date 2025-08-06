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


@pytest.fixture()
def cog(monkeypatch):
    os.environ.setdefault("HF_API_TOKEN", "dummy")
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    return DailyHeroDMCog(bot)


def test_generate_message_fallback(cog, monkeypatch):
    def fake_gen(*args, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Hello there"))]
        )
    monkeypatch.setattr(cog.hf_client, "chat_completion", fake_gen)
    msg = asyncio.run(cog._generate_message("Tester"))
    assert "Daily Hero role until midnight Pacific" in msg


def test_generate_message_success(cog, monkeypatch):
    sample = (
        "Greetings, Tester; your valiant efforts yesterday earned the Daily Hero honour, "
        "which persists until midnight, so cherish this well-deserved laurel in quiet, dignified triumph tonight."
    )
    def fake_gen(*args, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=sample))]
        )
    monkeypatch.setattr(cog.hf_client, "chat_completion", fake_gen)
    msg = asyncio.run(cog._generate_message("Tester"))
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

            async def send(self, message):
                sent.append(message)

        member = DummyMember()
        role = SimpleNamespace(members=[member])
        guild = SimpleNamespace(get_role=lambda _id: role)
        monkeypatch.setattr(cog.bot, "get_guild", lambda _id: guild)

        async def fake_generate(name):
            return "Hello Hero"

        monkeypatch.setattr(cog, "_generate_message", fake_generate)

        caplog.set_level(logging.INFO)
        await cog._send_dm()

        assert sent == ["Hello Hero"]
        assert any("Sent Daily Hero DM to Tester: Hello Hero" in r.message for r in caplog.records)

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
