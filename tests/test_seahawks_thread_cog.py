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
        schedule = [{"id": "g1", "opponent": "Rams", "short": "LAR @ SEA", "start": start}]
        monkeypatch.setattr(cog, "fetch_schedule", lambda: schedule)
        projection = {"sea_score": 24, "opp_score": 21, "sea_win": 0.55, "opp_win": 0.45}
        monkeypatch.setattr(cog, "fetch_projection", lambda gid: projection)

        created = []
        thread_types = []
        sent = []

        async def fake_create_thread(name, auto_archive_duration=None, type=None):
            created.append(name)
            thread_types.append(type)
            return SimpleNamespace(send=lambda msg: sent.append(msg))

        channel = SimpleNamespace(create_thread=fake_create_thread)
        monkeypatch.setattr(bot, "get_channel", lambda cid: channel)
        monkeypatch.setattr(discord, "TextChannel", SimpleNamespace)

        # run at 9:05am PST
        now = PST.localize(datetime(2024, 1, 1, 9, 5)).astimezone(timezone.utc)
        monkeypatch.setattr(cog, "_now", lambda: now)

        await cog._open_threads()
        assert created == ["🏈 LAR @ SEA (1/1, 5:30pm PST)"]
        assert thread_types == [discord.ChannelType.public_thread]
        assert "Projected score: Seahawks 24 - Rams 21" in sent[0]
        assert "Win odds: Seahawks 55.0%, Rams 45.0%" in sent[0]

    asyncio.run(run_test())


def test_fetch_schedule_skips_bye_week(monkeypatch):
    data = {
        "events": [
            {
                "id": "g1",
                "shortName": "SEA @ LAR",
                "competitions": [
                    {
                        "date": "2024-01-01T17:30Z",
                        "competitors": [
                            {"team": {"abbreviation": "SEA"}},
                            {
                                "team": {
                                    "abbreviation": "LAR",
                                    "displayName": "Rams",
                                }
                            },
                        ],
                    }
                ],
            },
            {
                "id": "bye1",
                "shortName": "BYE",
                "competitions": [
                    {
                        "date": "2024-10-01T17:30Z",
                        "competitors": [
                            {
                                "team": {
                                    "abbreviation": "SEA",
                                    "displayName": "Seahawks",
                                }
                            }
                        ],
                    }
                ],
            },
        ]
    }

    class FakeResp:
        def json(self):
            return data

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "gentlebot.cogs.seahawks_thread_cog.requests.get", lambda url, timeout=10: FakeResp()
    )

    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    monkeypatch.setattr(bot, "loop", SimpleNamespace(create_task=lambda c: None))
    monkeypatch.setattr(SeahawksThreadCog, "game_task", SimpleNamespace(start=lambda: None))
    cog = SeahawksThreadCog(bot)

    games = cog.fetch_schedule()
    assert len(games) == 1
    assert games[0]["opponent"] == "Rams"
    assert games[0]["short"] == "SEA @ LAR"
