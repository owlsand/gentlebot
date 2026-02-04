"""Weekly Yahoo Fantasy Football recap scheduler."""
from __future__ import annotations

import logging
from datetime import date

import aiohttp
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import discord
from discord import app_commands
from discord.ext import commands

from .. import bot_config as cfg
from ..db import get_pool
from ..infra import idempotent_task
from ..util import chan_name, user_name

from ..capabilities import (
    CogCapabilities,
    CommandCapability,
    ScheduledCapability,
    Category,
)

from ..tasks.yahoo_fantasy import (
    determine_target_week,
    extract_league_context,
    fetch_access_token,
    fetch_scoreboard,
    format_weekly_recap,
    parse_weekly_scoreboard,
    WeeklyRecap,
)

log = logging.getLogger(f"gentlebot.{__name__}")

LA = pytz.timezone("America/Los_Angeles")


class YahooFantasyWeeklyCog(commands.Cog):
    """Scheduler that posts the Yahoo Fantasy Football recap each Tuesday."""

    CAPABILITIES = CogCapabilities(
        commands=[
            CommandCapability(
                name="fantasyrecap",
                description="/fantasyrecap — Run the Yahoo Fantasy Football weekly recap",
                category=Category.SPORTS,
            ),
        ],
        scheduled=[
            ScheduledCapability(
                name="Fantasy Football Recap",
                schedule="Tuesday 9:00 AM PT",
                description="Weekly fantasy football scoreboard and standings (during season)",
                category=Category.SCHEDULED_WEEKLY,
            ),
        ],
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.pool = None
        self.scheduler: AsyncIOScheduler | None = None
        self._channel_id = getattr(cfg, "FANTASY_CHANNEL_ID", 0) or getattr(
            cfg, "SPORTS_CHANNEL_ID", 0
        )
        self._enabled = all(
            (
                getattr(cfg, "YAHOO_CLIENT_ID", None),
                getattr(cfg, "YAHOO_CLIENT_SECRET", None),
                getattr(cfg, "YAHOO_REFRESH_TOKEN", None),
                getattr(cfg, "YAHOO_LEAGUE_KEY", None),
            )
        )

    async def cog_load(self) -> None:
        if not self._enabled:
            log.warning("Yahoo Fantasy credentials missing; weekly recap disabled")
            return
        if not self._channel_id:
            log.warning("Fantasy recap channel ID not configured; weekly recap disabled")
            return
        # Get shared pool for idempotency tracking
        try:
            self.pool = await get_pool()
        except RuntimeError:
            log.warning("YahooFantasyWeekly: database pool unavailable")
            self.pool = None
        self.scheduler = AsyncIOScheduler(timezone=LA)
        trigger = CronTrigger(day_of_week="tue", hour=9, minute=0, timezone=LA)
        self.scheduler.add_job(self._post_weekly_recap_safe, trigger)
        self.scheduler.start()
        log.info("Yahoo Fantasy weekly scheduler started")

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        self.pool = None

    def _get_week_key(self) -> str:
        """Generate a weekly execution key: YYYY-WNN."""
        today = date.today()
        return f"{today.year}-W{today.isocalendar()[1]:02d}"

    async def _post_weekly_recap_safe(self) -> None:
        """Wrapper with error handling."""
        try:
            await self._post_weekly_recap()
        except Exception as exc:
            log.exception("Yahoo Fantasy weekly recap failed: %s", exc)

    @idempotent_task("yahoo_fantasy_weekly", lambda self: self._get_week_key())
    async def _post_weekly_recap(self) -> str:
        if not self._enabled:
            return "skipped:disabled"
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(self._channel_id)
        if not isinstance(channel, discord.TextChannel):
            log.error("Fantasy recap channel %s not found", self._channel_id)
            return "error:channel_not_found"
        try:
            message = await self._build_message()
        except Exception:  # pragma: no cover - defensive logging
            log.exception("Failed to build Yahoo Fantasy recap message")
            return "error:build_failed"
        if not message:
            log.info("Yahoo Fantasy recap skipped; no message generated")
            return "skipped:no_message"
        await channel.send(message)
        return "sent"

    @app_commands.command(
        name="fantasyrecap", description="Run the Yahoo Fantasy Football weekly recap"
    )
    async def slash_fantasy_recap(self, interaction: discord.Interaction) -> None:
        """Execute the Yahoo Fantasy weekly recap immediately."""
        log.info(
            "/fantasyrecap invoked by %s in %s",
            user_name(interaction.user),
            chan_name(interaction.channel),
        )
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not self._enabled:
            await interaction.followup.send(
                "Yahoo Fantasy credentials are not configured.", ephemeral=True
            )
            return

        try:
            message = await self._build_message()
        except Exception:  # pragma: no cover - defensive logging
            log.exception("Failed to build Yahoo Fantasy recap message from slash command")
            await interaction.followup.send(
                "Could not build the Yahoo Fantasy recap right now.", ephemeral=True
            )
            return

        if not message:
            await interaction.followup.send(
                "No Yahoo Fantasy recap is available yet.", ephemeral=True
            )
            return

        if len(message) <= 2000:
            await interaction.followup.send(message, ephemeral=True)
            return

        for chunk_start in range(0, len(message), 1900):
            await interaction.followup.send(message[chunk_start : chunk_start + 1900], ephemeral=True)

    async def _build_message(self) -> str | None:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            token = await fetch_access_token(
                session,
                client_id=cfg.YAHOO_CLIENT_ID,
                client_secret=cfg.YAHOO_CLIENT_SECRET,
                refresh_token=cfg.YAHOO_REFRESH_TOKEN,
            )
            payload = await fetch_scoreboard(
                session,
                access_token=token,
                league_key=cfg.YAHOO_LEAGUE_KEY,
                week=None,
            )
            context = extract_league_context(payload)
            target_week = determine_target_week(context)
            if target_week is None:
                log.info("Yahoo Fantasy season appears complete; skipping recap")
                return None

            recap: WeeklyRecap | None = None
            try:
                recap = parse_weekly_scoreboard(
                    payload,
                    fallback_name=context.name,
                    fallback_week=target_week,
                )
            except ValueError:
                recap = None

            if (target_week is not None and recap and recap.week != target_week) or recap is None:
                payload = await fetch_scoreboard(
                    session,
                    access_token=token,
                    league_key=cfg.YAHOO_LEAGUE_KEY,
                    week=target_week,
                )
                try:
                    recap = parse_weekly_scoreboard(
                        payload,
                        fallback_name=context.name,
                        fallback_week=target_week,
                    )
                except ValueError as exc:
                    log.warning("Yahoo Fantasy scoreboard parse failed: %s", exc)
                    return None

        if not recap.matchups:
            log.warning("Yahoo Fantasy scoreboard returned no matchups")
            return None
        if not recap.is_final():
            log.info("Yahoo Fantasy week %s scoreboard not final; skipping recap", recap.week)
            return None
        return format_weekly_recap(recap)
