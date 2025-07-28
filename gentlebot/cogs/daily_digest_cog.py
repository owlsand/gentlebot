"""Daily Digest Cog.
Posts daily summary and assigns tiered badges."""
from __future__ import annotations

from discord.ext import commands

from ..tasks.daily_digest import DailyDigestCog as _DailyDigestCog


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(_DailyDigestCog(bot))
