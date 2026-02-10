"""
welcome_back_cog.py – Lurker Re-engagement & Monthly Recap DMs
==============================================================
Re-engages inactive users with warm, in-channel welcome-back messages
and provides opt-in monthly recap DMs.

How it works:
  A. **Welcome-back detection** (on_message listener):
     When a user with Ghost or Lurker role posts a message:
     - Gap > 7 days: react with 👋
     - Gap > 14 days: also post a short welcome-back reply
     - Cooldown: 30 days between welcome-backs per user

  B. **Monthly recap DMs** (scheduled task, 1st of month):
     Opted-in users receive a personalized engagement recap via DM.

  C. **/recap** slash command:
     Toggle opt-in for monthly recap DMs.

Configuration in bot_config.py:
  • WELCOME_BACK_ENABLED: Master toggle (default: True)
  • WELCOME_BACK_MIN_GAP_DAYS: Minimum gap to trigger wave (default: 7)
  • WELCOME_BACK_COOLDOWN_DAYS: Cooldown between events (default: 30)
  • MONTHLY_RECAP_DM_ENABLED: Master toggle for DMs (default: True)
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import date

import discord
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord import app_commands
from discord.ext import commands

from .. import bot_config as cfg
from ..capabilities import (
    CogCapabilities,
    CommandCapability,
    ScheduledCapability,
    Category,
)
from ..infra import PoolAwareCog, require_pool, idempotent_task, monthly_key
from ..queries import engagement as eq
from ..util import user_name

log = logging.getLogger(f"gentlebot.{__name__}")

LA = pytz.timezone("America/Los_Angeles")

# Template pool for short welcome-back messages (< 14-day gap)
WELCOME_TEMPLATES = [
    "Welcome back, {name}! Good to see you around. 🙂",
    "Hey {name}, welcome back! We missed you.",
    "{name}'s back! Good to have you here again.",
    "Welcome back, {name}! Jump right in. 🙌",
]

# Inactivity role IDs for detection
_INACTIVITY_ROLES: set[int] = set()


def _get_inactivity_roles() -> set[int]:
    """Lazily build set of inactivity role IDs."""
    global _INACTIVITY_ROLES
    if not _INACTIVITY_ROLES:
        _INACTIVITY_ROLES = {
            r for r in (
                cfg.ROLE_GHOST,
                getattr(cfg, "ROLE_LURKER_FLAG", 0),
                getattr(cfg, "ROLE_SHADOW_FLAG", 0),
            ) if r
        }
    return _INACTIVITY_ROLES


class WelcomeBackCog(PoolAwareCog):
    """Welcomes back inactive users and sends monthly recap DMs."""

    CAPABILITIES = CogCapabilities(
        commands=[
            CommandCapability(
                name="recap",
                description="/recap — Toggle opt-in for monthly recap DMs",
                category=Category.ENGAGEMENT,
            ),
        ],
        scheduled=[
            ScheduledCapability(
                name="Monthly Recap DM",
                schedule="1st of month, 10 AM PT",
                description="Sends personalized recap DMs to opted-in users",
                category=Category.SCHEDULED_WEEKLY,
            ),
        ],
    )

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.scheduler: AsyncIOScheduler | None = None

    async def cog_load(self) -> None:
        await super().cog_load()

        if not cfg.WELCOME_BACK_ENABLED and not cfg.MONTHLY_RECAP_DM_ENABLED:
            log.info("WelcomeBackCog fully disabled")
            return

        self.scheduler = AsyncIOScheduler(timezone=LA)

        if cfg.MONTHLY_RECAP_DM_ENABLED:
            trigger = CronTrigger(day=1, hour=10, minute=0, timezone=LA)
            self.scheduler.add_job(self._send_monthly_recaps_safe, trigger)

        self.scheduler.start()
        log.info("WelcomeBackCog scheduler started")

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        await super().cog_unload()

    # ------------------------------------------------------------------
    # A. Welcome-back detection (on_message)
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    @require_pool
    async def on_message(self, message: discord.Message) -> None:
        """Detect returning lurkers and welcome them back."""
        if not cfg.WELCOME_BACK_ENABLED:
            return
        if message.author.bot or message.guild is None:
            return
        if message.guild.id != cfg.GUILD_ID:
            return

        member = message.author
        if not isinstance(member, discord.Member):
            return

        # Check if user has an inactivity role
        inactivity_roles = _get_inactivity_roles()
        user_role_ids = {r.id for r in member.roles}
        if not user_role_ids & inactivity_roles:
            return

        # Check cooldown: skip if we welcomed them recently
        recent = await self.pool.fetchval(
            """
            SELECT 1 FROM discord.welcome_back_event
            WHERE user_id = $1
              AND sent_at > now() - ($2 || ' days')::interval
            """,
            member.id,
            str(cfg.WELCOME_BACK_COOLDOWN_DAYS),
        )
        if recent:
            return

        # Calculate inactivity gap from last message
        last_msg_at = await self.pool.fetchval(
            """
            SELECT MAX(created_at) FROM discord.message
            WHERE author_id = $1
              AND message_id != $2
            """,
            member.id,
            message.id,
        )

        if last_msg_at is None:
            gap_days = 999  # Never posted before — treat as long gap
        else:
            gap_days = (discord.utils.utcnow() - last_msg_at).days

        min_gap = cfg.WELCOME_BACK_MIN_GAP_DAYS
        if gap_days < min_gap:
            return

        # React with 👋 for any qualifying gap
        try:
            await message.add_reaction("👋")
        except discord.HTTPException:
            log.warning("Failed to add wave reaction to message %s", message.id)

        # For longer gaps (2x min), also send a welcome-back message
        if gap_days >= min_gap * 2:
            template = random.choice(WELCOME_TEMPLATES)
            text = template.format(name=member.display_name)
            try:
                await message.reply(text, mention_author=False)
            except discord.HTTPException as exc:
                log.warning("Failed to send welcome-back message: %s", exc)

        # Record the event
        await self.pool.execute(
            """
            INSERT INTO discord.welcome_back_event (user_id, channel_id, gap_days)
            VALUES ($1, $2, $3)
            """,
            member.id,
            message.channel.id,
            gap_days,
        )

        log.info(
            "Welcome-back for %s (gap=%d days) in #%s",
            user_name(member),
            gap_days,
            getattr(message.channel, "name", "?"),
        )

    # ------------------------------------------------------------------
    # B. /recap slash command
    # ------------------------------------------------------------------

    @app_commands.command(
        name="recap",
        description="Toggle monthly recap DMs with your personal engagement stats",
    )
    async def recap(self, interaction: discord.Interaction) -> None:
        """Toggle opt-in for monthly recap DMs."""
        if not self.pool:
            await interaction.response.send_message(
                "Database unavailable — try again later.", ephemeral=True,
            )
            return

        user_id = interaction.user.id

        # Upsert preference (toggle)
        row = await self.pool.fetchrow(
            """
            INSERT INTO discord.user_recap_pref (user_id, opted_in)
            VALUES ($1, true)
            ON CONFLICT (user_id) DO UPDATE
                SET opted_in = NOT discord.user_recap_pref.opted_in
            RETURNING opted_in
            """,
            user_id,
        )

        opted_in = row["opted_in"]
        if opted_in:
            msg = (
                "You're now **opted in** to monthly recap DMs! "
                "On the 1st of each month, I'll send you a personalized "
                "engagement summary. Use `/recap` again to opt out."
            )
        else:
            msg = (
                "You've **opted out** of monthly recap DMs. "
                "Use `/recap` again anytime to re-subscribe."
            )

        await interaction.response.send_message(msg, ephemeral=True)
        log.info("/recap toggled by %s -> opted_in=%s", user_name(interaction.user), opted_in)

    # ------------------------------------------------------------------
    # C. Monthly recap DMs
    # ------------------------------------------------------------------

    async def _send_monthly_recaps_safe(self) -> None:
        """Error-handling wrapper for the monthly recap task."""
        try:
            await self._send_monthly_recaps()
        except Exception as exc:
            log.exception("Monthly recap DM task failed: %s", exc)

    @idempotent_task("monthly_recap_dm", monthly_key)
    async def _send_monthly_recaps(self) -> str:
        """Build and send personalized recap DMs to opted-in users."""
        await self.bot.wait_until_ready()

        if not self.pool:
            return "error:no_pool"

        # Get opted-in users
        rows = await self.pool.fetch(
            """
            SELECT user_id FROM discord.user_recap_pref
            WHERE opted_in = true
            """,
        )

        if not rows:
            log.info("No users opted in for monthly recap DMs")
            return "no_users"

        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            return "error:guild_not_found"

        interval = "30 days"
        sent = 0
        failed = 0

        for row in rows:
            user_id = row["user_id"]
            try:
                member = guild.get_member(user_id)
                if not member:
                    try:
                        member = await guild.fetch_member(user_id)
                    except discord.NotFound:
                        log.warning("Monthly recap: member %d not found", user_id)
                        continue
                    except discord.HTTPException:
                        continue

                embed = await self._build_recap_embed(member, interval)

                dm = await member.create_dm()
                await dm.send(embed=embed)
                sent += 1
                log.info("Sent monthly recap DM to %s", user_name(member))

                # Small delay to avoid rate limits
                await asyncio.sleep(2)

            except discord.Forbidden:
                log.warning("Cannot DM %d (DMs disabled)", user_id)
                failed += 1
            except Exception:
                log.exception("Failed to send recap DM to %d", user_id)
                failed += 1

        result = f"sent={sent}, failed={failed}"
        log.info("Monthly recap DMs complete: %s", result)
        return result

    async def _build_recap_embed(
        self, member: discord.Member, interval: str,
    ) -> discord.Embed:
        """Build a personalized recap embed for a user."""
        pool = self.pool
        user_id = member.id

        # Gather stats
        msg_count = await eq.user_message_count(pool, user_id, interval)
        reactions = await eq.user_reactions_received(pool, user_id, interval)
        top_channels = await eq.user_top_channels(pool, user_id, interval, limit=3)
        top_emojis = await eq.user_top_emojis_received(pool, user_id, interval, limit=5)
        msg_pct = await eq.user_message_percentile(pool, user_id, interval)
        peak_hour = await eq.user_peak_hour(pool, user_id, interval)

        embed = discord.Embed(
            title="📊 Your Monthly Recap",
            description=(
                f"Here's how your month looked in **{member.guild.name}**!"
            ),
            color=discord.Color.blue(),
        )

        # Activity summary
        pct_str = ""
        if msg_pct is not None:
            top_pct = round((1 - msg_pct) * 100)
            if top_pct <= 50:
                pct_str = f" (Top {max(top_pct, 1)}%)"
        embed.add_field(
            name="Messages",
            value=f"**{msg_count:,}** messages{pct_str}",
            inline=True,
        )
        embed.add_field(
            name="Reactions Received",
            value=f"**{reactions:,}** reactions",
            inline=True,
        )

        # Peak hour
        if peak_hour is not None:
            suffix = "AM" if peak_hour < 12 else "PM"
            display = peak_hour % 12 or 12
            embed.add_field(
                name="Peak Hour",
                value=f"**{display} {suffix} PT**",
                inline=True,
            )

        # Top channels
        if top_channels:
            lines = [f"#{name} ({cnt:,})" for _, name, cnt in top_channels]
            embed.add_field(
                name="Your Top Channels",
                value="\n".join(lines),
                inline=False,
            )

        # Top reactions received
        if top_emojis:
            emoji_text = " ".join(f"{emoji}×{cnt}" for emoji, cnt in top_emojis)
            embed.add_field(
                name="Top Reactions You Got",
                value=emoji_text,
                inline=False,
            )

        embed.set_footer(text="Use /recap to unsubscribe • Try /mystats anytime for live stats")
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeBackCog(bot))
