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

        async def fake_fetch():
            cog.last_category = "Engagement Bait"
            return "What is your favorite color?"

        monkeypatch.setattr(cog, "fetch_prompt", fake_fetch)

        class DummyDateTime:
            @classmethod
            def now(cls, tz=None):
                from datetime import datetime as real_datetime
                return real_datetime(2025, 7, 21, tzinfo=tz)

        monkeypatch.setattr(prompt_cog, "datetime", DummyDateTime)

        added = []

        class DummyThread(SimpleNamespace):
            id = 1

            async def send(self, msg):
                self.sent = msg

            async def add_user(self, member):
                added.append(member)

        created = []

        async def fake_create_thread(name, auto_archive_duration=None, type=None):
            created.append((name, type))
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

        assert created == [(
            "(Jul 21) What is your favorite color?",
            discord.ChannelType.public_thread,
        )]
        assert added == []

    asyncio.run(run_test())


def test_thread_name_truncates(monkeypatch):
    async def run_test():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = prompt_cog.PromptCog(bot)

        long_prompt = "A" * 200

        async def fake_fetch_long():
            cog.last_category = "Engagement Bait"
            return long_prompt

        monkeypatch.setattr(cog, "fetch_prompt", fake_fetch_long)

        class DummyDateTime:
            @classmethod
            def now(cls, tz=None):
                from datetime import datetime as real_datetime
                return real_datetime(2025, 7, 21, tzinfo=tz)

        monkeypatch.setattr(prompt_cog, "datetime", DummyDateTime)

        class DummyThread(SimpleNamespace):
            id = 1

            async def send(self, msg):
                pass

        created = []

        async def fake_create_thread(name, auto_archive_duration=None, type=None):
            created.append(name)
            return DummyThread()

        channel = SimpleNamespace(create_thread=fake_create_thread, guild=None)

        monkeypatch.setattr(bot, "get_channel", lambda cid: channel)
        monkeypatch.setattr(prompt_cog.cfg, "DAILY_PING_CHANNEL", 1)

        await cog._send_prompt()

        assert created
        assert created[0].startswith("(Jul 21) AAA")
        assert created[0].endswith("...")
        assert len(created[0]) == 100

    asyncio.run(run_test())

