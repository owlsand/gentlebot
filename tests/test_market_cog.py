import asyncio
import discord
from discord.ext import commands
from gentlebot.cogs import market_cog


def test_bets_exist(monkeypatch, tmp_path):
    async def run_test():
        db = tmp_path / "marketbet.db"
        monkeypatch.setattr(market_cog, "DB_PATH", str(db))
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = market_cog.MarketCog(bot)
        cog.summary_task.cancel()
        cog.reminder_task.cancel()
        week = "2023-01-02"
        assert not cog._bets_exist(week)
        assert cog._place_bet(1, week, "bullish", 50)
        assert cog._bets_exist(week)
        await cog.bot.close()
    asyncio.run(run_test())
