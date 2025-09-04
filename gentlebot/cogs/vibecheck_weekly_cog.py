"""Cog wrapper to schedule weekly vibe checks."""
from __future__ import annotations

from discord.ext import commands

from ..tasks.vibecheck_weekly import WeeklyVibeCheckCog as _WeeklyVibeCheckCog


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(_WeeklyVibeCheckCog(bot))

