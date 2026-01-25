"""Monthly personal recaps for Gentlebot.

Sends personalized monthly engagement recap DMs to opted-in users on the 1st
of each month, summarizing their previous month's activity.
"""
from __future__ import annotations

import asyncio
import logging
from calendar import month_name
from datetime import date, timedelta
from typing import TYPE_CHECKING

import discord
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord import app_commands
from discord.ext import commands

from .. import bot_config as cfg
from ..infra import PoolAwareCog, alert_task_failure, idempotent_task, monthly_key
from ..llm.router import SafetyBlocked, router
from ..infra.quotas import RateLimited

if TYPE_CHECKING:
    import asyncpg

log = logging.getLogger(f"gentlebot.{__name__}")

LA = pytz.timezone("America/Los_Angeles")

PROMPT_TEMPLATE = """You are Gentlebot composing a friendly monthly recap DM to {user_name}.

Stats for {month_name}:
- Messages sent: {message_count}
- Reactions received: {reactions_received}
- Top channels: {top_channels}
- Current engagement streak: {current_streak} days
- Best streak ever: {longest_streak} days

Write a 2-3 sentence personalized recap that highlights their engagement.
Be warm and encouraging. If they have a notable streak, mention it.
If they were particularly active in certain channels, acknowledge it.
End with a brief positive note about the new month.

Output only the message text. No markdown formatting, no quotation marks."""

FALLBACK_TEMPLATE = """Hey {user_name}! Your Gentlefolk recap for {month_name}: You sent {message_count} messages and earned {reactions_received} reactions. {streak_note}Keep the vibes going! \U0001f916 Gentlebot"""


class MonthlyRecapCog(PoolAwareCog):
    """Sends personalized monthly recap DMs to opted-in users."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.scheduler: AsyncIOScheduler | None = None
        self.temperature = 0.7

    async def cog_load(self) -> None:
        await super().cog_load()
        self.scheduler = AsyncIOScheduler(timezone=LA)
        # Run at 10:00 AM Pacific on the 1st of each month
        trigger = CronTrigger(day=1, hour=10, minute=0, timezone=LA)
        self.scheduler.add_job(self._send_recaps_safe, trigger)
        self.scheduler.start()
        log.info("MonthlyRecapCog scheduler started")

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        await super().cog_unload()

    # ── Database Operations ────────────────────────────────────────────────

    async def _get_opted_in_users(self) -> list[int]:
        """Get all users who have opted in to monthly recaps."""
        if not self.pool:
            return []

        rows = await self.pool.fetch(
            """
            SELECT user_id FROM discord.user_recap_pref
            WHERE opted_in = TRUE
            """
        )
        return [r["user_id"] for r in rows]

    async def _set_opted_in(self, user_id: int, value: bool) -> None:
        """Set or update a user's recap opt-in preference."""
        if not self.pool:
            return

        await self.pool.execute(
            """
            INSERT INTO discord.user_recap_pref (user_id, opted_in, created_at)
            VALUES ($1, $2, now())
            ON CONFLICT (user_id) DO UPDATE SET opted_in = EXCLUDED.opted_in
            """,
            user_id,
            value,
        )

    async def _is_opted_in(self, user_id: int) -> bool:
        """Check if a user is opted in to recaps."""
        if not self.pool:
            return False

        row = await self.pool.fetchrow(
            """
            SELECT opted_in FROM discord.user_recap_pref
            WHERE user_id = $1
            """,
            user_id,
        )
        return bool(row and row["opted_in"])

    async def _gather_user_stats(
        self, user_id: int, start: date, end: date
    ) -> dict:
        """Aggregate user's stats for the given date range."""
        if not self.pool:
            return {
                "message_count": 0,
                "reactions_received": 0,
                "top_channels": [],
                "current_streak": 0,
                "longest_streak": 0,
            }

        # Message count
        msg_row = await self.pool.fetchrow(
            """
            SELECT COUNT(*) as cnt
            FROM discord.message m
            WHERE m.author_id = $1
              AND m.created_at >= $2
              AND m.created_at < $3
            """,
            user_id,
            start,
            end,
        )
        message_count = msg_row["cnt"] if msg_row else 0

        # Reactions received
        react_row = await self.pool.fetchrow(
            """
            SELECT COUNT(*) as cnt
            FROM discord.reaction_event r
            JOIN discord.message m ON r.message_id = m.message_id
            WHERE m.author_id = $1
              AND r.reaction_action = 'MESSAGE_REACTION_ADD'
              AND r.event_at >= $2
              AND r.event_at < $3
            """,
            user_id,
            start,
            end,
        )
        reactions_received = react_row["cnt"] if react_row else 0

        # Top channels
        channel_rows = await self.pool.fetch(
            """
            SELECT c.name, COUNT(*) as cnt
            FROM discord.message m
            JOIN discord.channel c ON m.channel_id = c.channel_id
            WHERE m.author_id = $1
              AND m.created_at >= $2
              AND m.created_at < $3
            GROUP BY c.name
            ORDER BY cnt DESC
            LIMIT 3
            """,
            user_id,
            start,
            end,
        )
        top_channels = [r["name"] for r in channel_rows]

        # Current streak
        streak_row = await self.pool.fetchrow(
            """
            SELECT current_streak, longest_streak
            FROM discord.user_streak
            WHERE user_id = $1
            """,
            user_id,
        )
        current_streak = streak_row["current_streak"] if streak_row else 0
        longest_streak = streak_row["longest_streak"] if streak_row else 0

        return {
            "message_count": message_count,
            "reactions_received": reactions_received,
            "top_channels": top_channels,
            "current_streak": current_streak,
            "longest_streak": longest_streak,
        }

    # ── Message Generation ─────────────────────────────────────────────────

    def _build_prompt(
        self, user_name: str, month_str: str, stats: dict
    ) -> str:
        """Build the LLM prompt for recap generation."""
        channels_str = (
            ", ".join(f"#{c}" for c in stats["top_channels"])
            if stats["top_channels"]
            else "various channels"
        )
        return PROMPT_TEMPLATE.format(
            user_name=user_name,
            month_name=month_str,
            message_count=stats["message_count"],
            reactions_received=stats["reactions_received"],
            top_channels=channels_str,
            current_streak=stats["current_streak"],
            longest_streak=stats["longest_streak"],
        )

    def _fallback_message(
        self, user_name: str, month_str: str, stats: dict
    ) -> str:
        """Generate a fallback message without LLM."""
        streak_note = ""
        if stats["current_streak"] >= 7:
            streak_note = f"You're on a {stats['current_streak']}-day streak! "
        elif stats["longest_streak"] >= 7:
            streak_note = f"Your best streak was {stats['longest_streak']} days. "

        return FALLBACK_TEMPLATE.format(
            user_name=user_name,
            month_name=month_str,
            message_count=stats["message_count"],
            reactions_received=stats["reactions_received"],
            streak_note=streak_note,
        )

    async def _generate_recap_message(
        self, user_name: str, month_str: str, stats: dict
    ) -> str:
        """Generate personalized recap message using LLM with fallback."""
        prompt = self._build_prompt(user_name, month_str, stats)

        try:
            text = await asyncio.to_thread(
                router.generate,
                "scheduled",
                [{"role": "user", "content": prompt}],
                self.temperature,
            )
            text = text.strip().replace("\n", " ")
            if len(text) < 20:
                # Too short, use fallback
                return self._fallback_message(user_name, month_str, stats)
            return text
        except (RateLimited, SafetyBlocked) as e:
            log.warning("Recap generation blocked: %s", e)
            return self._fallback_message(user_name, month_str, stats)
        except Exception as e:
            log.exception("Recap generation failed: %s", e)
            return self._fallback_message(user_name, month_str, stats)

    # ── Scheduled Task ─────────────────────────────────────────────────────

    async def _send_recaps_safe(self) -> None:
        """Wrapper for _send_recaps with error handling."""
        try:
            await self._send_recaps()
        except Exception as exc:
            log.exception("Monthly recap task failed: %s", exc)
            await alert_task_failure(
                self.bot,
                "monthly_recap",
                exc,
                context={"month": monthly_key(self)},
            )

    @idempotent_task("monthly_recap", monthly_key)
    async def _send_recaps(self) -> str:
        """Send monthly recap DMs to all opted-in users."""
        await self.bot.wait_until_ready()

        if not self.pool:
            return "error:no_pool"

        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            log.error("Guild not found")
            return "error:guild_not_found"

        # Calculate previous month's date range
        today = date.today()
        first_of_this_month = today.replace(day=1)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        first_of_prev_month = last_of_prev_month.replace(day=1)
        month_str = month_name[last_of_prev_month.month]

        log.info(
            "Sending monthly recaps for %s (%s to %s)",
            month_str,
            first_of_prev_month,
            last_of_prev_month,
        )

        opted_in_users = await self._get_opted_in_users()
        log.info("Found %d opted-in users", len(opted_in_users))

        sent_count = 0
        failed_count = 0

        for user_id in opted_in_users:
            member = guild.get_member(user_id)
            if not member:
                continue

            stats = await self._gather_user_stats(
                user_id, first_of_prev_month, first_of_this_month
            )

            # Skip users with no activity
            if stats["message_count"] == 0:
                continue

            message = await self._generate_recap_message(
                member.display_name, month_str, stats
            )

            try:
                await member.send(message)
                log.info("Sent monthly recap to %s", member.display_name)
                sent_count += 1
            except discord.HTTPException as e:
                log.warning("Failed to send recap to %s: %s", member.display_name, e)
                failed_count += 1

            # Rate limit: small delay between DMs
            await asyncio.sleep(1)

        result = f"sent:{sent_count},failed:{failed_count}"
        log.info("Monthly recap task complete: %s", result)
        return result

    # ── Slash Commands ─────────────────────────────────────────────────────

    recap_group = app_commands.Group(
        name="recap", description="Monthly recap preferences"
    )

    @recap_group.command(name="optin", description="Opt in to monthly recap DMs")
    async def recap_optin(self, interaction: discord.Interaction) -> None:
        """Enable monthly recap DMs for the user."""
        await self._set_opted_in(interaction.user.id, True)
        await interaction.response.send_message(
            "\u2705 You're now opted in to monthly recap DMs! "
            "You'll receive a personalized summary on the 1st of each month.",
            ephemeral=True,
        )

    @recap_group.command(name="optout", description="Opt out of monthly recap DMs")
    async def recap_optout(self, interaction: discord.Interaction) -> None:
        """Disable monthly recap DMs for the user."""
        await self._set_opted_in(interaction.user.id, False)
        await interaction.response.send_message(
            "\u274c You've opted out of monthly recap DMs. "
            "You can opt back in anytime with `/recap optin`.",
            ephemeral=True,
        )

    @recap_group.command(name="view", description="Preview your current month's stats")
    async def recap_view(self, interaction: discord.Interaction) -> None:
        """Show a preview of the user's current month stats."""
        if not self.pool:
            await interaction.response.send_message(
                "Database unavailable.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        today = date.today()
        first_of_month = today.replace(day=1)
        month_str = month_name[today.month]

        stats = await self._gather_user_stats(
            interaction.user.id, first_of_month, today + timedelta(days=1)
        )

        opted_in = await self._is_opted_in(interaction.user.id)
        opt_status = "\u2705 Opted in" if opted_in else "\u274c Not opted in"

        channels_str = (
            ", ".join(f"#{c}" for c in stats["top_channels"])
            if stats["top_channels"]
            else "None yet"
        )

        embed = discord.Embed(
            title=f"\U0001f4ca {month_str} Stats Preview",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Messages", value=str(stats["message_count"]), inline=True
        )
        embed.add_field(
            name="Reactions Received",
            value=str(stats["reactions_received"]),
            inline=True,
        )
        embed.add_field(name="Top Channels", value=channels_str, inline=False)
        embed.add_field(
            name="Current Streak",
            value=f"{stats['current_streak']} days",
            inline=True,
        )
        embed.add_field(
            name="Best Streak",
            value=f"{stats['longest_streak']} days",
            inline=True,
        )
        embed.add_field(name="Recap DMs", value=opt_status, inline=True)

        embed.set_footer(
            text="This shows your activity so far this month. "
            "Full recaps are sent on the 1st."
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @recap_group.command(name="status", description="Check your recap opt-in status")
    async def recap_status(self, interaction: discord.Interaction) -> None:
        """Check the user's current opt-in status."""
        opted_in = await self._is_opted_in(interaction.user.id)

        if opted_in:
            await interaction.response.send_message(
                "\u2705 You're opted in to monthly recap DMs. "
                "Use `/recap optout` to disable.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "\u274c You're not opted in to monthly recap DMs. "
                "Use `/recap optin` to enable.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MonthlyRecapCog(bot))
