"""Weekly VibeCheck scheduler.

Posts the `/vibecheck` report in #lobby every Monday at 9am Pacific."""
from __future__ import annotations

import logging

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import discord
from discord.ext import commands

from .. import bot_config as cfg
from .vibecheck_cog import VibeCheckCog

log = logging.getLogger(f"gentlebot.{__name__}")

LA = pytz.timezone("America/Los_Angeles")


class WeeklyVibeCheckCog(commands.Cog):
    """Scheduler that posts a weekly vibe check in the lobby."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler: AsyncIOScheduler | None = None

    async def cog_load(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone=LA)
        trigger = CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=LA)
        self.scheduler.add_job(self._run_vibecheck, trigger)
        self.scheduler.start()
        log.info("Weekly VibeCheck scheduler started")

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None

    async def _run_vibecheck(self) -> None:
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(cfg.LOBBY_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            log.error("Lobby channel not found")
            return
        cog = self.bot.get_cog("VibeCheckCog")
        if not isinstance(cog, VibeCheckCog):
            log.error("VibeCheckCog not loaded")
            return
        embed = await cog.build_embed(
            self.bot.get_guild(cfg.GUILD_ID), llm_route="scheduled"
        )
        if not embed:
            log.error("Vibe report unavailable")
            return
        await channel.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WeeklyVibeCheckCog(bot))

