"""Daily Haiku Cog.
Posts a daily haiku summary in #lobby."""
from __future__ import annotations

from discord.ext import commands

from ..tasks.daily_haiku import DailyHaikuCog as _DailyHaikuCog


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(_DailyHaikuCog(bot))
