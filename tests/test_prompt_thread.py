import asyncio
from types import SimpleNamespace
import discord
from discord.ext import commands

from gentlebot.cogs import prompt_cog


def test_send_prompt_creates_thread(monkeypatch):
    async def run_test():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = prompt_cog.PromptCog(bot)

        monkeypatch.setattr(cog, "fetch_prompt", lambda: "What is your favorite color?")

        class DummyDateTime:
            @classmethod
            def now(cls, tz=None):
                from datetime import datetime as real_datetime
                return real_datetime(2025, 7, 21, tzinfo=tz)

        monkeypatch.setattr(prompt_cog, "datetime", DummyDateTime)

        added = []

        class DummyThread(SimpleNamespace):
            async def send(self, msg):
                self.sent = msg
            async def add_user(self, member):
                added.append(member)

        created = []

        async def fake_create_thread(name, auto_archive_duration=None):
            created.append(name)
            return DummyThread()

        guild = SimpleNamespace(
            members=[
                SimpleNamespace(id=1, bot=False),
                SimpleNamespace(id=2, bot=False),
            ]
        )
        channel = SimpleNamespace(create_thread=fake_create_thread, guild=guild)

        monkeypatch.setattr(bot, "get_channel", lambda cid: channel)
        monkeypatch.setattr(prompt_cog.cfg, "DAILY_PING_CHANNEL", 1)

        await cog._send_prompt()

        assert created == ["QOTD Jul 21"]
        assert added == guild.members

    asyncio.run(run_test())

