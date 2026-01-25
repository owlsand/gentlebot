"""Engagement streak tracking for Gentlebot.

Tracks consecutive daily engagement streaks and awards milestone roles:
- 7 days: Week Warrior
- 14 days: Fortnight Fighter
- 30 days: Month Master
- 60 days: Iron Will
- 100 days: Century Club

Also announces milestone achievements publicly to celebrate user accomplishments.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

import discord
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord import app_commands
from discord.ext import commands

from .. import bot_config as cfg
from ..infra import PoolAwareCog, alert_task_failure, daily_key, idempotent_task
from ..llm.router import get_router, SafetyBlocked

if TYPE_CHECKING:
    import asyncpg

log = logging.getLogger(f"gentlebot.{__name__}")

LA = pytz.timezone("America/Los_Angeles")

# Streak milestone thresholds
MILESTONES = sorted(cfg.STREAK_ROLES.keys())  # [7, 14, 30, 60, 100]

# Role names for logging
MILESTONE_NAMES = {
    7: "Week Warrior",
    14: "Fortnight Fighter",
    30: "Month Master",
    60: "Iron Will",
    100: "Century Club",
}

# Bitmask positions for announced milestones tracking
# bit 0 = 7-day, bit 1 = 14-day, bit 2 = 30-day, bit 3 = 60-day, bit 4 = 100-day
MILESTONE_BITS = {
    7: 0,
    14: 1,
    30: 2,
    60: 3,
    100: 4,
}

# Celebration titles for each milestone
MILESTONE_TITLES = {
    7: "\U0001f525 Week Warrior Unlocked!",
    14: "\U0001f525\U0001f525 Fortnight Fighter Unlocked!",
    30: "\u2b50 Month Master Unlocked!",
    60: "\U0001f4aa Iron Will Unlocked!",
    100: "\U0001f451 Century Club Unlocked!",
}

# Embed colors for each milestone tier
MILESTONE_COLORS = {
    7: discord.Color.red(),
    14: discord.Color.orange(),
    30: discord.Color.blue(),
    60: discord.Color.purple(),
    100: discord.Color.gold(),
}


class StreakCog(PoolAwareCog):
    """Tracks engagement streaks and assigns milestone roles."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.scheduler: AsyncIOScheduler | None = None

    async def cog_load(self) -> None:
        await super().cog_load()
        self.scheduler = AsyncIOScheduler(timezone=LA)
        # Run at 12:05 AM Pacific daily
        trigger = CronTrigger(hour=0, minute=5, timezone=LA)
        self.scheduler.add_job(self._maintain_streaks_safe, trigger)
        self.scheduler.start()
        log.info("StreakCog scheduler started")
        # Schedule backfill to run after bot is ready
        self.bot.loop.create_task(self._backfill_streaks_on_ready())

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        await super().cog_unload()

    # ── Startup Backfill ───────────────────────────────────────────────────

    async def _backfill_streaks_on_ready(self) -> None:
        """Backfill streak data from message history on bot startup."""
        await self.bot.wait_until_ready()

        if not self.pool:
            log.warning("No pool available for streak backfill")
            return

        try:
            await self._backfill_streaks()
        except Exception as exc:
            log.exception("Streak backfill failed: %s", exc)

    async def _backfill_streaks(self) -> None:
        """Calculate and update streaks from message history for all users."""
        log.info("Starting streak backfill from message history...")

        # Get all distinct non-bot users with messages, grouped by date
        rows = await self.pool.fetch(
            """
            SELECT
                m.author_id,
                (m.created_at AT TIME ZONE 'America/Los_Angeles')::date AS activity_date
            FROM discord.message m
            JOIN discord."user" u ON m.author_id = u.user_id
            WHERE u.is_bot IS NOT TRUE
              AND m.created_at >= now() - INTERVAL '365 days'
            GROUP BY m.author_id, (m.created_at AT TIME ZONE 'America/Los_Angeles')::date
            ORDER BY m.author_id, activity_date
            """
        )

        if not rows:
            log.info("No message history found for streak backfill")
            return

        # Group activity dates by user
        user_dates: dict[int, list[date]] = {}
        for row in rows:
            uid = row["author_id"]
            activity_date = row["activity_date"]
            if uid not in user_dates:
                user_dates[uid] = []
            user_dates[uid].append(activity_date)

        today_la = date.today()
        updated = 0
        skipped = 0

        for user_id, dates in user_dates.items():
            # Check if user already has streak data
            existing = await self.pool.fetchrow(
                """
                SELECT current_streak, longest_streak, last_active_date
                FROM discord.user_streak
                WHERE user_id = $1
                """,
                user_id,
            )

            # Skip if user already has meaningful streak data (not just default 1)
            if existing and existing["current_streak"] > 1:
                skipped += 1
                continue

            # Sort dates and calculate streak
            sorted_dates = sorted(set(dates))

            # Calculate current streak (consecutive days ending at today or yesterday)
            current_streak = 0
            check_date = today_la
            for d in reversed(sorted_dates):
                if d == check_date or d == check_date - timedelta(days=1):
                    current_streak += 1
                    check_date = d - timedelta(days=1)
                elif d < check_date - timedelta(days=1):
                    break

            # Calculate longest streak ever
            longest_streak = 0
            streak = 1
            for i in range(1, len(sorted_dates)):
                if sorted_dates[i] - sorted_dates[i - 1] == timedelta(days=1):
                    streak += 1
                else:
                    longest_streak = max(longest_streak, streak)
                    streak = 1
            longest_streak = max(longest_streak, streak)

            # Determine streak start date
            if current_streak > 0:
                streak_started = sorted_dates[-1] - timedelta(days=current_streak - 1)
                last_active = sorted_dates[-1]
            else:
                streak_started = None
                last_active = sorted_dates[-1] if sorted_dates else None

            # Update or insert streak record
            await self.pool.execute(
                """
                INSERT INTO discord.user_streak (
                    user_id, current_streak, longest_streak, last_active_date,
                    streak_started_date, announced_milestones, updated_at
                ) VALUES ($1, $2, $3, $4, $5, 0, now())
                ON CONFLICT (user_id) DO UPDATE SET
                    current_streak = GREATEST(discord.user_streak.current_streak, EXCLUDED.current_streak),
                    longest_streak = GREATEST(discord.user_streak.longest_streak, EXCLUDED.longest_streak),
                    last_active_date = COALESCE(EXCLUDED.last_active_date, discord.user_streak.last_active_date),
                    streak_started_date = COALESCE(EXCLUDED.streak_started_date, discord.user_streak.streak_started_date),
                    updated_at = now()
                """,
                user_id,
                current_streak,
                longest_streak,
                last_active,
                streak_started,
            )
            updated += 1

        log.info("Streak backfill complete: %d users updated, %d skipped", updated, skipped)

    # ── Helper Methods ─────────────────────────────────────────────────────

    def _streak_emoji(self, streak: int) -> str:
        """Return emoji based on streak length."""
        if streak >= 100:
            return "\U0001f451"  # Crown
        elif streak >= 60:
            return "\U0001f4aa"  # Flexed biceps
        elif streak >= 30:
            return "\u2b50"      # Star
        elif streak >= 14:
            return "\U0001f525\U0001f525"  # Double fire
        elif streak >= 7:
            return "\U0001f525"  # Fire
        elif streak >= 3:
            return "\U0001f31f"  # Glowing star
        else:
            return "\U0001f331"  # Seedling

    def _streak_color(self, streak: int) -> discord.Color:
        """Return embed color based on streak length."""
        if streak >= 100:
            return discord.Color.gold()
        elif streak >= 60:
            return discord.Color.purple()
        elif streak >= 30:
            return discord.Color.blue()
        elif streak >= 14:
            return discord.Color.orange()
        elif streak >= 7:
            return discord.Color.red()
        else:
            return discord.Color.green()

    def _next_milestone(self, current: int) -> int | None:
        """Return the next milestone to reach, or None if at max."""
        for ms in MILESTONES:
            if current < ms:
                return ms
        return None

    # ── Bitmask Helpers for Announced Milestones ───────────────────────────

    def _milestone_announced(self, announced_bitmask: int, milestone: int) -> bool:
        """Check if a milestone has already been announced."""
        bit_position = MILESTONE_BITS.get(milestone)
        if bit_position is None:
            return False
        return bool(announced_bitmask & (1 << bit_position))

    def _mark_milestone_announced(self, announced_bitmask: int, milestone: int) -> int:
        """Return new bitmask with milestone marked as announced."""
        bit_position = MILESTONE_BITS.get(milestone)
        if bit_position is None:
            return announced_bitmask
        return announced_bitmask | (1 << bit_position)

    # ── Milestone Announcements ────────────────────────────────────────────

    async def _generate_celebration_message(
        self, member: discord.Member, milestone: int, streak: int
    ) -> str | None:
        """Generate a personalized celebration message using LLM."""
        if not cfg.MILESTONE_LLM_ENABLED:
            return None

        try:
            router = get_router()
            prompt = (
                f"Write a short, enthusiastic congratulatory message (1-2 sentences max) for {member.display_name} "
                f"who just reached a {milestone}-day engagement streak on Discord. "
                f"Their total streak is now {streak} days. Be warm and encouraging but concise. "
                f"Don't use the word 'journey' or start with 'Congratulations'. "
                f"Sign as 'Gentlebot'."
            )
            messages = [{"role": "user", "content": prompt}]
            response = router.generate(
                "general",
                messages,
                temperature=0.8,
                system_instruction="You are Gentlebot, a friendly Discord bot. Write brief, warm celebratory messages.",
            )
            return response.strip()
        except SafetyBlocked:
            log.warning("LLM celebration message blocked by safety filter")
            return None
        except Exception as exc:
            log.warning("Failed to generate celebration message: %s", exc)
            return None

    async def _announce_milestone(
        self,
        guild: discord.Guild,
        user_id: int,
        milestone: int,
        streak: int,
    ) -> bool:
        """Post a public celebration embed for a milestone achievement."""
        # Get the announcement channel
        channel_id = cfg.MILESTONE_CHANNEL_ID or getattr(cfg, "LOBBY_CHANNEL_ID", 0)
        if not channel_id:
            log.warning("No milestone announcement channel configured")
            return False

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            log.warning("Milestone channel %d not found or not a text channel", channel_id)
            return False

        # Get the member
        member = guild.get_member(user_id)
        if not member:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                log.warning("Could not fetch member %d for milestone announcement", user_id)
                return False

        # Build the embed
        title = MILESTONE_TITLES.get(milestone, f"\U0001f525 {milestone}-Day Streak!")
        color = MILESTONE_COLORS.get(milestone, discord.Color.orange())

        embed = discord.Embed(
            title=title,
            description=f"Congratulations {member.mention}! You've reached **{streak}** consecutive days!",
            color=color,
        )

        # Try to add LLM-generated personalized message
        llm_message = await self._generate_celebration_message(member, milestone, streak)
        if llm_message:
            embed.add_field(name="From Gentlebot", value=llm_message, inline=False)

        embed.set_footer(text="Keep the streak alive!")
        embed.set_thumbnail(url=member.display_avatar.url)

        try:
            await channel.send(embed=embed)
            log.info(
                "Announced %d-day milestone for %s in channel %d",
                milestone,
                member.display_name,
                channel_id,
            )
            return True
        except discord.HTTPException as exc:
            log.warning("Failed to send milestone announcement: %s", exc)
            return False

    # ── Database Operations ────────────────────────────────────────────────

    async def _get_user_streak(self, user_id: int) -> dict:
        """Fetch streak info for a user."""
        if not self.pool:
            return {"current": 0, "longest": 0, "last_active": None, "started": None, "announced": 0}

        row = await self.pool.fetchrow(
            """
            SELECT current_streak, longest_streak, last_active_date, streak_started_date,
                   COALESCE(announced_milestones, 0) AS announced_milestones
            FROM discord.user_streak
            WHERE user_id = $1
            """,
            user_id,
        )
        if row:
            return {
                "current": row["current_streak"],
                "longest": row["longest_streak"],
                "last_active": row["last_active_date"],
                "started": row["streak_started_date"],
                "announced": row["announced_milestones"],
            }
        return {"current": 0, "longest": 0, "last_active": None, "started": None, "announced": 0}

    async def _get_active_users_yesterday(self) -> list[int]:
        """Find users who posted at least one message yesterday (LA timezone)."""
        if not self.pool:
            return []

        today_la = date.today()
        yesterday_la = today_la - timedelta(days=1)

        rows = await self.pool.fetch(
            """
            SELECT DISTINCT m.author_id
            FROM discord.message m
            JOIN discord."user" u ON m.author_id = u.user_id
            WHERE m.created_at >= $1::date AT TIME ZONE 'America/Los_Angeles'
              AND m.created_at < $2::date AT TIME ZONE 'America/Los_Angeles'
              AND u.is_bot IS NOT TRUE
            """,
            yesterday_la,
            today_la,
        )
        return [r["author_id"] for r in rows]

    async def _update_streak(
        self,
        user_id: int,
        new_streak: int,
        longest: int,
        active_date: date,
        started_date: date | None,
        announced_milestones: int = 0,
    ) -> None:
        """Update or insert a user's streak record."""
        if not self.pool:
            return

        await self.pool.execute(
            """
            INSERT INTO discord.user_streak (
                user_id, current_streak, longest_streak, last_active_date, streak_started_date,
                announced_milestones, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, now())
            ON CONFLICT (user_id) DO UPDATE SET
                current_streak = EXCLUDED.current_streak,
                longest_streak = EXCLUDED.longest_streak,
                last_active_date = EXCLUDED.last_active_date,
                streak_started_date = EXCLUDED.streak_started_date,
                announced_milestones = EXCLUDED.announced_milestones,
                updated_at = now()
            """,
            user_id,
            new_streak,
            longest,
            active_date,
            started_date,
            announced_milestones,
        )

    async def _reset_streak(self, user_id: int) -> None:
        """Reset a user's current streak to 0."""
        if not self.pool:
            return

        await self.pool.execute(
            """
            UPDATE discord.user_streak
            SET current_streak = 0, streak_started_date = NULL, updated_at = now()
            WHERE user_id = $1
            """,
            user_id,
        )

    # ── Role Sync ──────────────────────────────────────────────────────────

    async def _sync_streak_roles(
        self, guild: discord.Guild, user_id: int, streak: int
    ) -> None:
        """Assign appropriate streak roles based on current streak."""
        member = guild.get_member(user_id)
        if not member:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                return

        if cfg.STREAK_ROLES_CUMULATIVE:
            # Cumulative: Add all roles up to current streak, remove higher ones
            for milestone in MILESTONES:
                role_id = cfg.STREAK_ROLES.get(milestone, 0)
                if role_id == 0:
                    continue
                role = guild.get_role(role_id)
                if not role:
                    continue

                if streak >= milestone and role not in member.roles:
                    try:
                        await member.add_roles(
                            role, reason=f"Streak milestone: {milestone} days"
                        )
                        log.info(
                            "Assigned %s role to %s (streak: %d)",
                            MILESTONE_NAMES.get(milestone, str(milestone)),
                            member.display_name,
                            streak,
                        )
                    except discord.HTTPException as e:
                        log.warning(
                            "Failed to assign streak role %d to %s: %s",
                            milestone,
                            member.display_name,
                            e,
                        )
                elif streak < milestone and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Streak reset")
                        log.info(
                            "Removed %s role from %s (streak reset)",
                            MILESTONE_NAMES.get(milestone, str(milestone)),
                            member.display_name,
                        )
                    except discord.HTTPException as e:
                        log.warning(
                            "Failed to remove streak role %d from %s: %s",
                            milestone,
                            member.display_name,
                            e,
                        )
        else:
            # Exclusive: Only the highest earned role
            earned = max((m for m in MILESTONES if streak >= m), default=0)

            for milestone in MILESTONES:
                role_id = cfg.STREAK_ROLES.get(milestone, 0)
                if role_id == 0:
                    continue
                role = guild.get_role(role_id)
                if not role:
                    continue

                should_have = milestone == earned

                if should_have and role not in member.roles:
                    try:
                        await member.add_roles(
                            role, reason=f"Streak milestone: {milestone} days"
                        )
                        log.info(
                            "Assigned %s role to %s (streak: %d)",
                            MILESTONE_NAMES.get(milestone, str(milestone)),
                            member.display_name,
                            streak,
                        )
                    except discord.HTTPException as e:
                        log.warning(
                            "Failed to assign streak role %d to %s: %s",
                            milestone,
                            member.display_name,
                            e,
                        )
                elif not should_have and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Streak level changed")
                        log.info(
                            "Removed %s role from %s (upgraded to higher tier)",
                            MILESTONE_NAMES.get(milestone, str(milestone)),
                            member.display_name,
                        )
                    except discord.HTTPException as e:
                        log.warning(
                            "Failed to remove streak role %d from %s: %s",
                            milestone,
                            member.display_name,
                            e,
                        )

    async def _remove_all_streak_roles(
        self, guild: discord.Guild, user_id: int
    ) -> None:
        """Remove all streak roles from a user (on streak reset)."""
        member = guild.get_member(user_id)
        if not member:
            return

        for milestone in MILESTONES:
            role_id = cfg.STREAK_ROLES.get(milestone, 0)
            if role_id == 0:
                continue
            role = guild.get_role(role_id)
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Streak reset")
                    log.info(
                        "Removed %s role from %s (streak reset)",
                        MILESTONE_NAMES.get(milestone, str(milestone)),
                        member.display_name,
                    )
                except discord.HTTPException as e:
                    log.warning(
                        "Failed to remove streak role from %s: %s",
                        member.display_name,
                        e,
                    )

    # ── Scheduled Task ─────────────────────────────────────────────────────

    async def _maintain_streaks_safe(self) -> None:
        """Wrapper for _maintain_streaks with error handling."""
        try:
            await self._maintain_streaks()
        except Exception as exc:
            log.exception("Streak maintenance task failed: %s", exc)
            await alert_task_failure(
                self.bot,
                "streak_maintenance",
                exc,
                context={"date": date.today().isoformat()},
            )

    @idempotent_task("streak_maintenance", daily_key)
    async def _maintain_streaks(self) -> str:
        """Daily task to update all streaks and sync roles."""
        await self.bot.wait_until_ready()

        if not self.pool:
            return "error:no_pool"

        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            log.error("Guild not found")
            return "error:guild_not_found"

        today_la = date.today()
        yesterday_la = today_la - timedelta(days=1)

        # Get users who were active yesterday
        active_users = await self._get_active_users_yesterday()
        active_set = set(active_users)

        log.info("Processing streaks for %d active users", len(active_users))

        # Get all existing streak records
        rows = await self.pool.fetch(
            """
            SELECT user_id, current_streak, longest_streak, last_active_date, streak_started_date,
                   COALESCE(announced_milestones, 0) AS announced_milestones
            FROM discord.user_streak
            """
        )

        updated = 0
        reset = 0
        new_milestones = 0
        announced = 0

        # Update existing streaks
        for row in rows:
            user_id = row["user_id"]
            current = row["current_streak"]
            longest = row["longest_streak"]
            last_active = row["last_active_date"]
            started = row["streak_started_date"]
            announced_bitmask = row["announced_milestones"]

            if user_id in active_set:
                # User was active yesterday
                if last_active == yesterday_la - timedelta(days=1):
                    # Continuing streak
                    new_streak = current + 1
                    new_longest = max(longest, new_streak)

                    # Check for new milestone and announce if needed
                    old_milestone = max((m for m in MILESTONES if current >= m), default=0)
                    new_milestone = max((m for m in MILESTONES if new_streak >= m), default=0)

                    new_announced_bitmask = announced_bitmask
                    if new_milestone > old_milestone:
                        new_milestones += 1
                        log.info(
                            "User %d reached %d-day milestone!",
                            user_id,
                            new_milestone,
                        )

                        # Check if this milestone needs to be announced
                        if not self._milestone_announced(announced_bitmask, new_milestone):
                            if await self._announce_milestone(guild, user_id, new_milestone, new_streak):
                                new_announced_bitmask = self._mark_milestone_announced(
                                    announced_bitmask, new_milestone
                                )
                                announced += 1

                    await self._update_streak(
                        user_id, new_streak, new_longest, yesterday_la, started, new_announced_bitmask
                    )
                    await self._sync_streak_roles(guild, user_id, new_streak)
                    updated += 1
                elif last_active != yesterday_la:
                    # Streak was broken, starting fresh
                    # Keep announced_bitmask - don't reset announcements when streak breaks
                    await self._update_streak(user_id, 1, longest, yesterday_la, yesterday_la, announced_bitmask)
                    await self._remove_all_streak_roles(guild, user_id)
                    reset += 1
                # else: already processed today (last_active == yesterday_la)

                active_set.discard(user_id)
            else:
                # User was NOT active yesterday
                if current > 0 and last_active < yesterday_la:
                    # Streak broken
                    await self._reset_streak(user_id)
                    await self._remove_all_streak_roles(guild, user_id)
                    reset += 1

        # Create records for newly active users
        for user_id in active_set:
            await self._update_streak(user_id, 1, 1, yesterday_la, yesterday_la, 0)
            updated += 1

        result = f"updated:{updated},reset:{reset},milestones:{new_milestones},announced:{announced}"
        log.info("Streak maintenance complete: %s", result)
        return result

    # ── Slash Commands ─────────────────────────────────────────────────────

    @app_commands.command(name="streak", description="Check your engagement streak")
    @app_commands.describe(user="User to check (defaults to yourself)")
    async def streak(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        """Display streak info for self or mentioned user."""
        target = user or interaction.user
        streak_info = await self._get_user_streak(target.id)

        current = streak_info["current"]
        longest = streak_info["longest"]
        next_ms = self._next_milestone(current)

        embed = discord.Embed(
            title=f"{self._streak_emoji(current)} {target.display_name}'s Streak",
            color=self._streak_color(current),
        )
        embed.add_field(name="Current", value=f"{current} days", inline=True)
        embed.add_field(name="Best Ever", value=f"{longest} days", inline=True)

        if next_ms:
            days_to_go = next_ms - current
            embed.add_field(
                name="Next Milestone",
                value=f"{MILESTONE_NAMES.get(next_ms, f'{next_ms} days')} ({days_to_go} to go)",
                inline=True,
            )
        elif current >= max(MILESTONES):
            embed.add_field(
                name="Status",
                value="\U0001f451 Century Club member!",
                inline=True,
            )

        if streak_info["started"]:
            embed.set_footer(text=f"Streak started: {streak_info['started']}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="streakboard", description="Show top streak holders")
    async def streakboard(self, interaction: discord.Interaction) -> None:
        """Display streak leaderboard."""
        if not self.pool:
            await interaction.response.send_message(
                "Database unavailable.", ephemeral=True
            )
            return

        rows = await self.pool.fetch(
            """
            SELECT user_id, current_streak, longest_streak
            FROM discord.user_streak
            WHERE current_streak > 0
            ORDER BY current_streak DESC, longest_streak DESC
            LIMIT 10
            """
        )

        if not rows:
            await interaction.response.send_message(
                "No active streaks yet! Start posting to build your streak.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        lines = []
        for i, row in enumerate(rows, 1):
            user_id = row["user_id"]
            current = row["current_streak"]
            longest = row["longest_streak"]

            member = guild.get_member(user_id) if guild else None
            name = member.display_name if member else f"User {user_id}"

            medal = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}.get(i, f"{i}.")
            emoji = self._streak_emoji(current)

            lines.append(
                f"{medal} {emoji} **{name}** - {current} days (best: {longest})"
            )

        embed = discord.Embed(
            title="\U0001f525 Streak Leaderboard",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Keep posting daily to climb the board!")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StreakCog(bot))
