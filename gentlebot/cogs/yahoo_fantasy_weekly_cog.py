"""Cog wrapper to schedule the Yahoo Fantasy Football weekly recap."""
from __future__ import annotations

from discord.ext import commands

from ..tasks.yahoo_fantasy_weekly import YahooFantasyWeeklyCog as _YahooFantasyWeeklyCog


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(_YahooFantasyWeeklyCog(bot))
