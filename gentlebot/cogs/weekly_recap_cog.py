"""Weekly server recap posted every Monday at 9:30 AM PT."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

import discord
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord.ext import commands

from .. import bot_config as cfg
from ..infra import PoolAwareCog, idempotent_task, weekly_key
from ..infra.quotas import RateLimited
from ..llm.router import SafetyBlocked, router
from ..capabilities import (
    CogCapabilities,
    ScheduledCapability,
    Category,
)
from ..queries import engagement as eq

log = logging.getLogger(f"gentlebot.{__name__}")

LA = pytz.timezone("America/Los_Angeles")

INTERVAL = timedelta(days=7)
PREV_INTERVAL = timedelta(days=14)  # used for week-over-week delta


def _week_range_title() -> str:
    """Return 'Jan 27 to Feb 2' style title for the past 7 days."""
    today = date.today()
    start = today - timedelta(days=7)
    return f"{start.strftime('%b %-d')} to {(today - timedelta(days=1)).strftime('%b %-d')}"


def _delta_str(current: int, previous_total: int) -> str:
    """Compute week-over-week delta as 'up 15%' / 'down 8%' / ''."""
    # previous_total covers 14 days; the *previous* week is total minus current
    prev = previous_total - current
    if prev <= 0:
        return ""
    pct = round((current - prev) / prev * 100)
    if pct > 0:
        return f" (up {pct}%)"
    elif pct < 0:
        return f" (down {abs(pct)}%)"
    return ""


async def _generate_vibe(stats: dict, guild_name: str) -> str:
    """Use the LLM to produce a one-sentence vibe summary.

    Falls back to a simple template on any failure.
    """
    fallback = f"Here's what happened in {guild_name} this week."
    if not cfg.WEEKLY_RECAP_LLM_ENABLED:
        return fallback
    try:
        prompt = (
            f"Given these Discord server stats for the past week: {stats}. "
            "Write one witty sentence (under 100 chars) characterizing the week. "
            "No emojis. No hashtags."
        )
        messages = [{"role": "user", "content": prompt}]
        response = await asyncio.to_thread(
            router.generate,
            "scheduled",
            messages,
            temperature=0.9,
            system_instruction=(
                "You are a witty community observer. Write exactly one short sentence."
            ),
        )
        text = response.strip().strip('"')
        return text if len(text) < 200 else fallback
    except (SafetyBlocked, RateLimited):
        return fallback
    except Exception as exc:
        log.warning("LLM vibe generation failed: %s", exc)
        return fallback


class WeeklyRecapCog(PoolAwareCog):
    """Posts a weekly engagement recap every Monday morning."""

    CAPABILITIES = CogCapabilities(
        scheduled=[
            ScheduledCapability(
                name="Weekly Recap",
                schedule="Mon 9:30 AM PT",
                description="Posts a server engagement recap with top posters, reactions, and community pulse",
                category=Category.SCHEDULED_WEEKLY,
            ),
        ],
    )

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.scheduler: AsyncIOScheduler | None = None

    async def cog_load(self) -> None:
        await super().cog_load()
        if not cfg.WEEKLY_RECAP_ENABLED:
            log.info("WeeklyRecapCog disabled via WEEKLY_RECAP_ENABLED")
            return
        self.scheduler = AsyncIOScheduler(timezone=LA)
        trigger = CronTrigger(day_of_week="mon", hour=9, minute=30, timezone=LA)
        self.scheduler.add_job(self._post_recap_safe, trigger)
        self.scheduler.start()
        log.info("WeeklyRecapCog scheduler started (Mon 9:30 AM PT)")

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        await super().cog_unload()

    # ------------------------------------------------------------------
    # Scheduled task
    # ------------------------------------------------------------------

    async def _post_recap_safe(self) -> None:
        """Error-handling wrapper for the recap task."""
        try:
            await self._post_recap()
        except Exception as exc:
            log.exception("Weekly recap task failed: %s", exc)

    @idempotent_task("weekly_recap", weekly_key)
    async def _post_recap(self) -> str:
        """Build and post the weekly recap embed."""
        await self.bot.wait_until_ready()

        channel_id = cfg.WEEKLY_RECAP_CHANNEL_ID or cfg.LOBBY_CHANNEL_ID
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            log.error("Weekly recap channel %d not found", channel_id)
            return "error:channel_not_found"

        embed = await self._build_recap_embed(channel.guild)
        await channel.send(embed=embed)
        log.info("Weekly recap posted to #%s", channel.name)
        return "posted"

    # ------------------------------------------------------------------
    # Embed builder (public for testability)
    # ------------------------------------------------------------------

    async def _build_recap_embed(
        self, guild: discord.Guild,
    ) -> discord.Embed:
        """Assemble the full weekly recap embed."""
        pool = self.pool

        # Current week stats
        msg_count = await eq.server_message_count(pool, INTERVAL)
        posters = await eq.unique_posters(pool, INTERVAL)
        top_post = await eq.top_posters(pool, INTERVAL, limit=5)
        top_react = await eq.top_reaction_receivers(pool, INTERVAL, limit=5)
        hot_channels = await eq.most_active_channels(pool, INTERVAL, limit=5)
        top_msg = await eq.top_reacted_message(pool, INTERVAL)
        new_members = await eq.new_member_count(pool, INTERVAL)
        streaks = await eq.active_streak_counts(pool)
        hof = await eq.new_hof_count(pool, INTERVAL)

        # Previous 14-day total for week-over-week delta
        prev_msg_count = await eq.server_message_count(pool, PREV_INTERVAL)

        # LLM vibe summary
        stats_dict = {
            "messages": msg_count,
            "unique_posters": posters,
            "top_channels": [(n, c) for _, n, c in hot_channels[:3]],
        }
        vibe = await _generate_vibe(stats_dict, guild.name)

        delta = _delta_str(msg_count, prev_msg_count)

        # Build embed
        title = f"Weekly Recap \u2014 {_week_range_title()}"
        embed = discord.Embed(
            title=title,
            description=f"*{vibe}*",
            color=discord.Color.teal(),
        )

        # Top Posters
        if top_post:
            lines = []
            for i, (uid, cnt) in enumerate(top_post, 1):
                lines.append(f"{i}. <@{uid}> \u2014 {cnt:,} msgs")
            embed.add_field(name="Top Posters", value="\n".join(lines), inline=True)

        # Reaction Magnets
        if top_react:
            lines = []
            for i, (uid, cnt) in enumerate(top_react, 1):
                lines.append(f"{i}. <@{uid}> \u2014 {cnt:,} reactions")
            embed.add_field(
                name="Reaction Magnets", value="\n".join(lines), inline=True,
            )

        # Hot Channels
        if hot_channels:
            parts = [f"#{name} ({cnt:,})" for _, name, cnt in hot_channels]
            embed.add_field(
                name="Hot Channels",
                value=" \u00b7 ".join(parts),
                inline=False,
            )

        # Message of the Week
        if top_msg:
            content_preview = top_msg["content"] or ""
            if len(content_preview) > 120:
                content_preview = content_preview[:117] + "..."
            # Build jump URL
            guild_id = guild.id
            jump = (
                f"https://discord.com/channels/{guild_id}"
                f"/{top_msg['channel_id']}/{top_msg['message_id']}"
            )
            motw = (
                f"\"{content_preview}\" \u2014 <@{top_msg['author_id']}>"
                f" in #{top_msg['channel_name']}"
                f" ({top_msg['reaction_count']} reactions)\n"
                f"[Jump to message]({jump})"
            )
            embed.add_field(name="Message of the Week", value=motw, inline=False)

        # Community Pulse
        pulse_parts = [
            f"**{msg_count:,}** messages from **{posters}** people{delta}",
        ]
        if hof > 0:
            pulse_parts.append(f"**{hof}** new Hall of Fame entr{'y' if hof == 1 else 'ies'}")
        total_streaks, strong = streaks
        if total_streaks > 0:
            streak_text = f"**{total_streaks}** active streaks"
            if strong > 0:
                streak_text += f" ({strong} at 7+ days)"
            pulse_parts.append(streak_text)
        if new_members > 0:
            pulse_parts.append(
                f"**{new_members}** new member{'s' if new_members != 1 else ''}"
            )
        embed.add_field(
            name="Community Pulse",
            value=" \u00b7 ".join(pulse_parts),
            inline=False,
        )

        embed.set_footer(text="Curious about your own stats? Try /mystats")
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WeeklyRecapCog(bot))
