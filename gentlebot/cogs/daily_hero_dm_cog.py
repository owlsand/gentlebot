"""Cog wrapper to schedule Daily Hero congratulation DMs."""
from __future__ import annotations

from discord.ext import commands

from ..tasks.daily_hero_dm import DailyHeroDMCog as _DailyHeroDMCog


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(_DailyHeroDMCog(bot))
