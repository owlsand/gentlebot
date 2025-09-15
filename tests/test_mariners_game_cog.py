import asyncio
from types import SimpleNamespace
from datetime import datetime

import discord
from discord.ext import commands

from gentlebot.cogs import mariners_game_cog


SUMMARY = {
    "game_pk": 123,
    "mariners_home": False,
    "away_abbr": "SEA",
    "home_abbr": "HOU",
    "mariners_score": 5,
    "opp_score": 3,
    "opp_name": "Astros",
    "opp_abbr": "HOU",
    "start_pst": mariners_game_cog.PST_TZ.localize(datetime(2024, 9, 17, 13, 10)),
    "highlights": [
        "Rodríguez 2-run HR (7th)",
        "Crawford 2B",
        "Muñoz nails down the save.",
    ],
    "record": "82–66 (W2)",
    "al_west": "2nd • 1.5 GB of HOU • Last 10: 7–3",
    "top_performers": {
        "SEA": "Julio Rodríguez: 2-4, HR (28), 2 RBI | George Kirby: 7.0 IP, 6 K, 1 ER",
        "HOU": "Yordan Álvarez: 1-3, HR (34), 2 RBI | Framber Valdez: 6.0 IP, 2 ER, 7 K",
    },
}


def test_build_message():
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    cog = mariners_game_cog.MarinersGameCog(bot)
    msg = cog.build_message(SUMMARY)
    assert "SEA @ HOU" in msg
    assert "Mariners 5 — Astros 3" in msg
    assert "Top Performers" in msg


def test_posts_summary(monkeypatch):
    async def run_test():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = mariners_game_cog.MarinersGameCog(bot)
        monkeypatch.setattr(cog, "fetch_game_summary", lambda: SUMMARY)

        sent = []
        class DummyChannel(SimpleNamespace):
            async def send(self, content):
                sent.append(content)
        monkeypatch.setattr(bot, "get_channel", lambda cid: DummyChannel())
        monkeypatch.setattr(discord, "TextChannel", DummyChannel)
        async def dummy_wait():
            return None
        monkeypatch.setattr(bot, "wait_until_ready", dummy_wait)

        await mariners_game_cog.MarinersGameCog.game_task.coro(cog)
        assert sent
        assert "Mariners 5 — Astros 3" in sent[0]

    asyncio.run(run_test())
