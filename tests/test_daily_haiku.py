import asyncio
import os
from types import SimpleNamespace

import pytest
import discord
from discord.ext import commands
from apscheduler.triggers.cron import CronTrigger

from gentlebot import bot_config as cfg
from gentlebot.tasks.daily_haiku import DailyHaikuCog, build_prompt
from gentlebot.llm.router import router


@pytest.fixture()
def cog(monkeypatch):
    os.environ.setdefault("GEMINI_API_KEY", "dummy")
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    return DailyHaikuCog(bot)


def test_build_prompt():
    prompt = build_prompt("2024-05-15", "hello\nworld")
    assert "You are a concise poet" in prompt["system"]
    assert "DATE: 2024-05-15" in prompt["user"]
    assert "hello" in prompt["user"]


def test_haiku_scheduled(cog, monkeypatch):
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

    import gentlebot.tasks.daily_haiku as module

    monkeypatch.setattr(module, "AsyncIOScheduler", DummyScheduler)

    asyncio.run(cog.cog_load())

    trigger = captured.get("trigger")
    assert isinstance(trigger, CronTrigger)
    assert "hour='22'" in str(trigger)
    assert "minute='0'" in str(trigger)


def test_post_haiku_posts_message(cog, monkeypatch):
    async def run_test():
        async def dummy_wait():
            pass

        monkeypatch.setattr(cog.bot, "wait_until_ready", dummy_wait)
        monkeypatch.setattr(cfg, "GUILD_ID", 1, raising=False)
        monkeypatch.setattr(cfg, "LOBBY_CHANNEL_ID", 2, raising=False)

        class DummyPool:
            async def fetch(self, q, guild_id, start, end):
                return [{"content": "one"}, {"content": "two"}]

            async def close(self):
                pass

        cog.pool = DummyPool()

        monkeypatch.setattr(
            router,
            "generate",
            lambda route, msgs, temp=0.6, think_budget=0, json_mode=False: "line1\nline2\nline3",
        )

        sent: list[str] = []
        import gentlebot.tasks.daily_haiku as module

        class DummyChannel(SimpleNamespace):
            async def send(self, message):
                sent.append(message)

        monkeypatch.setattr(module.discord, "TextChannel", DummyChannel)
        channel = DummyChannel()
        monkeypatch.setattr(cog.bot, "get_channel", lambda cid: channel)

        await cog._post_haiku()
        assert sent == ["line1\nline2\nline3"]

    asyncio.run(run_test())
