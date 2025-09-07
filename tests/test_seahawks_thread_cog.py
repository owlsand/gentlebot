import asyncio
from types import SimpleNamespace
from datetime import datetime, timezone

import discord
from discord.ext import commands
from gentlebot.cogs.seahawks_thread_cog import SeahawksThreadCog, PST


def test_opens_thread_with_projection(monkeypatch):
    async def run_test():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        monkeypatch.setattr(bot, "loop", SimpleNamespace(create_task=lambda c: None))
        cog = SeahawksThreadCog(bot)
        # prevent background loop start
        monkeypatch.setattr(cog, "game_task", SimpleNamespace(start=lambda: None))

        start = PST.localize(datetime(2024, 1, 1, 17, 30)).astimezone(timezone.utc)
        schedule = [
            {"id": "g1", "opponent": "Rams", "short_name": "LAR @ SEA", "start": start}
        ]
        monkeypatch.setattr(cog, "fetch_schedule", lambda: schedule)
        projection = {"sea_score": 24, "opp_score": 21, "sea_win": 0.55, "opp_win": 0.45}
        monkeypatch.setattr(cog, "fetch_projection", lambda gid: projection)

        created = []
        sent = []

        async def fake_create_thread(name, auto_archive_duration=None):
            created.append(name)
            return SimpleNamespace(send=lambda msg: sent.append(msg))

        channel = SimpleNamespace(create_thread=fake_create_thread)
        monkeypatch.setattr(bot, "get_channel", lambda cid: channel)
        monkeypatch.setattr(discord, "TextChannel", SimpleNamespace)

        # run at 9:05am PST
        now = PST.localize(datetime(2024, 1, 1, 9, 5)).astimezone(timezone.utc)
        monkeypatch.setattr(cog, "_now", lambda: now)

        await cog._open_threads()
        assert created == ["🏈 LAR @ SEA (1/1, 5:30pm PST)"]
        assert "Projected score: Seahawks 24 - Rams 21" in sent[0]
        assert "Win odds: Seahawks 55.0%, Rams 45.0%" in sent[0]

    asyncio.run(run_test())
