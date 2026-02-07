"""Hall of Fame: Community-curated archive of exceptional messages.

Messages that receive high engagement (10+ reactions) get automatically nominated
with a trophy emoji. Community members vote by tapping the trophy, and messages
reaching the vote threshold (3 votes) are inducted into the Hall of Fame.

User Flow:
1. Message gets 10+ reactions -> Bot adds trophy emoji (nomination)
2. Community members tap trophy to vote
3. 3 votes reached -> Cross-post to #hall-of-fame channel
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord.ext import commands

from .. import bot_config as cfg
from ..capabilities import (
    Category,
    CogCapabilities,
    ReactionCapability,
    ScheduledCapability,
)
from ..infra import PoolAwareCog, log_errors, require_pool

if TYPE_CHECKING:
    import asyncpg

log = logging.getLogger(f"gentlebot.{__name__}")

LA = pytz.timezone("America/Los_Angeles")


class HallOfFameCog(PoolAwareCog):
    """Tracks high-engagement messages and manages Hall of Fame induction."""

    CAPABILITIES = CogCapabilities(
        reactions=[
            ReactionCapability(
                emoji=cfg.HOF_EMOJI,
                trigger="Nominated messages",
                description="Vote to induct a message into the Hall of Fame",
            ),
        ],
        scheduled=[
            ScheduledCapability(
                name="Hall of Fame Nominations",
                schedule="Every 30 minutes",
                description="Checks for messages with 10+ reactions and nominates them",
                category=Category.SCHEDULED_DAILY,
            ),
        ],
    )

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.scheduler: AsyncIOScheduler | None = None

    async def cog_load(self) -> None:
        await super().cog_load()

        if not cfg.HALL_OF_FAME_ENABLED:
            log.info("Hall of Fame feature is disabled")
            return

        # Start scheduler for periodic nomination checks
        self.scheduler = AsyncIOScheduler(timezone=LA)
        # Run every 30 minutes
        trigger = CronTrigger(minute="*/30", timezone=LA)
        self.scheduler.add_job(self._check_nominations_safe, trigger)
        self.scheduler.start()
        log.info("HallOfFameCog scheduler started")

        # Run initial check after bot is ready
        self.bot.loop.create_task(self._initial_nomination_check())

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        await super().cog_unload()

    async def _initial_nomination_check(self) -> None:
        """Run nomination check once bot is ready."""
        await self.bot.wait_until_ready()
        if self.pool and cfg.HALL_OF_FAME_ENABLED:
            try:
                await self._check_nominations()
            except Exception as exc:
                log.exception("Initial nomination check failed: %s", exc)

    # ── Nomination Detection ──────────────────────────────────────────────

    async def _check_nominations_safe(self) -> None:
        """Wrapper for _check_nominations with error handling."""
        if not cfg.HALL_OF_FAME_ENABLED:
            return
        try:
            await self._check_nominations()
        except Exception as exc:
            log.exception("Nomination check failed: %s", exc)

    @require_pool
    async def _check_nominations(self) -> None:
        """Find messages with 10+ reactions and nominate them."""
        await self.bot.wait_until_ready()

        threshold = cfg.HOF_NOMINATION_THRESHOLD
        lookback_days = 7  # Only check messages from last 7 days

        # Find messages with enough reactions that aren't already nominated
        # We count distinct reactions (user+emoji combos) per message
        rows = await self.pool.fetch(
            """
            WITH reaction_counts AS (
                SELECT
                    re.message_id,
                    COUNT(DISTINCT (re.user_id, re.emoji)) AS reaction_count
                FROM discord.reaction_event re
                WHERE re.reaction_action = 'MESSAGE_REACTION_ADD'
                  AND re.event_at >= NOW() - INTERVAL '%s days'
                  AND re.message_id IS NOT NULL
                GROUP BY re.message_id
                HAVING COUNT(DISTINCT (re.user_id, re.emoji)) >= $1
            )
            SELECT
                rc.message_id,
                rc.reaction_count,
                m.channel_id,
                m.author_id,
                m.content
            FROM reaction_counts rc
            JOIN discord.message m ON rc.message_id = m.message_id
            JOIN discord.channel c ON m.channel_id = c.channel_id
            JOIN discord."user" u ON m.author_id = u.user_id
            WHERE NOT EXISTS (
                SELECT 1 FROM discord.hall_of_fame hof
                WHERE hof.message_id = rc.message_id
            )
            AND c.is_private = FALSE
            AND u.is_bot IS NOT TRUE
            ORDER BY rc.reaction_count DESC
            LIMIT 20
            """ % lookback_days,
            threshold,
        )

        if not rows:
            log.debug("No new messages qualify for Hall of Fame nomination")
            return

        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            log.warning("Guild not found for Hall of Fame nominations")
            return

        nominated = 0
        for row in rows:
            message_id = row["message_id"]
            channel_id = row["channel_id"]
            author_id = row["author_id"]

            try:
                # Get the channel and message
                channel = guild.get_channel(channel_id)
                if not isinstance(channel, discord.TextChannel):
                    continue

                message = await channel.fetch_message(message_id)

                # Add trophy reaction to nominate
                await message.add_reaction(cfg.HOF_EMOJI)

                # Record nomination in database
                await self.pool.execute(
                    """
                    INSERT INTO discord.hall_of_fame (message_id, channel_id, author_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (message_id) DO NOTHING
                    """,
                    message_id,
                    channel_id,
                    author_id,
                )

                log.info(
                    "Nominated message %d for Hall of Fame (%d reactions)",
                    message_id,
                    row["reaction_count"],
                )
                nominated += 1

            except discord.NotFound:
                log.debug("Message %d not found, skipping nomination", message_id)
            except discord.Forbidden:
                log.warning("Cannot add reaction to message %d", message_id)
            except Exception as exc:
                log.warning("Failed to nominate message %d: %s", message_id, exc)

        if nominated > 0:
            log.info("Nominated %d messages for Hall of Fame", nominated)

    # ── Vote Handling ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    @log_errors("Hall of Fame vote handling failed")
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Handle trophy reactions for Hall of Fame voting."""
        if not cfg.HALL_OF_FAME_ENABLED:
            return

        # Only process trophy emoji
        if str(payload.emoji) != cfg.HOF_EMOJI:
            return

        # Ignore bot's own reactions
        if payload.user_id == self.bot.user.id:
            return

        # Ignore DMs
        if not payload.guild_id:
            return

        if not self.pool:
            return

        message_id = payload.message_id

        # Check if this message is nominated but not yet inducted
        row = await self.pool.fetchrow(
            """
            SELECT entry_id, vote_count, inducted_at, channel_id, author_id
            FROM discord.hall_of_fame
            WHERE message_id = $1
            """,
            message_id,
        )

        if not row:
            # Message not nominated, ignore
            return

        if row["inducted_at"] is not None:
            # Already inducted, ignore additional votes
            return

        # Increment vote count and check threshold
        new_count = row["vote_count"] + 1
        threshold = cfg.HOF_VOTE_THRESHOLD

        if new_count >= threshold:
            # Induct into Hall of Fame!
            await self._induct_message(
                message_id=message_id,
                channel_id=row["channel_id"],
                author_id=row["author_id"],
                entry_id=row["entry_id"],
                vote_count=new_count,
            )
        else:
            # Just update vote count
            await self.pool.execute(
                """
                UPDATE discord.hall_of_fame
                SET vote_count = $1
                WHERE entry_id = $2 AND inducted_at IS NULL
                """,
                new_count,
                row["entry_id"],
            )
            log.debug(
                "Vote recorded for message %d (%d/%d)",
                message_id,
                new_count,
                threshold,
            )

    # ── Induction ─────────────────────────────────────────────────────────

    async def _induct_message(
        self,
        message_id: int,
        channel_id: int,
        author_id: int,
        entry_id: int,
        vote_count: int,
    ) -> None:
        """Cross-post a message to the Hall of Fame channel."""
        hof_channel_id = cfg.HALL_OF_FAME_CHANNEL_ID
        if not hof_channel_id:
            log.warning("Hall of Fame channel not configured, skipping induction")
            return

        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            return

        hof_channel = guild.get_channel(hof_channel_id)
        if not isinstance(hof_channel, discord.TextChannel):
            log.warning("Hall of Fame channel %d not found or not a text channel", hof_channel_id)
            return

        # Fetch the original message
        source_channel = guild.get_channel(channel_id)
        if not isinstance(source_channel, discord.TextChannel):
            log.warning("Source channel %d not found", channel_id)
            return

        try:
            message = await source_channel.fetch_message(message_id)
        except discord.NotFound:
            log.warning("Original message %d not found, cannot induct", message_id)
            # Mark as inducted anyway to prevent retries
            await self.pool.execute(
                """
                UPDATE discord.hall_of_fame
                SET inducted_at = NOW(), vote_count = $1
                WHERE entry_id = $2
                """,
                vote_count,
                entry_id,
            )
            return

        # Count total reactions on the message
        total_reactions = sum(r.count for r in message.reactions)

        # Build the Hall of Fame embed
        embed = discord.Embed(
            title=f"{cfg.HOF_EMOJI} HALL OF FAME {cfg.HOF_EMOJI}",
            color=discord.Color.gold(),
            timestamp=message.created_at,
        )

        # Message content preview (max 500 chars)
        content = message.content or ""
        if len(content) > 500:
            content = content[:497] + "..."

        if content:
            embed.description = content

        # Handle attachments
        if message.attachments:
            first_attachment = message.attachments[0]
            if first_attachment.content_type and first_attachment.content_type.startswith("image/"):
                embed.set_image(url=first_attachment.url)

        # Add author info
        author = guild.get_member(author_id)
        if author:
            embed.set_author(
                name=author.display_name,
                icon_url=author.display_avatar.url,
            )

        # Footer with metadata
        embed.add_field(
            name="\u200b",  # Zero-width space for visual separator
            value=(
                f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
                f"\U0001f4dd {message.author.mention} in {source_channel.mention}\n"
                f"\U0001f517 [Jump to message]({message.jump_url})\n"
                f"\u2764\ufe0f {total_reactions} reactions"
            ),
            inline=False,
        )

        try:
            hof_message = await hof_channel.send(embed=embed)

            # Update database with induction info
            await self.pool.execute(
                """
                UPDATE discord.hall_of_fame
                SET inducted_at = NOW(), vote_count = $1, hof_message_id = $2
                WHERE entry_id = $3
                """,
                vote_count,
                hof_message.id,
                entry_id,
            )

            log.info(
                "Inducted message %d into Hall of Fame (hof_message_id=%d)",
                message_id,
                hof_message.id,
            )

        except discord.Forbidden:
            log.warning("Cannot send to Hall of Fame channel %d", hof_channel_id)
        except Exception as exc:
            log.exception("Failed to induct message %d: %s", message_id, exc)

    # ── Message Deletion Handling ─────────────────────────────────────────

    @commands.Cog.listener()
    @log_errors("Hall of Fame message deletion handling failed")
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        """Remove nomination if the original message is deleted."""
        if not cfg.HALL_OF_FAME_ENABLED:
            return

        if not self.pool:
            return

        # Check if this was a nominated message
        result = await self.pool.execute(
            """
            DELETE FROM discord.hall_of_fame
            WHERE message_id = $1 AND inducted_at IS NULL
            """,
            payload.message_id,
        )

        if result and "DELETE 1" in result:
            log.info("Removed Hall of Fame nomination for deleted message %d", payload.message_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HallOfFameCog(bot))
