"""Trending content discovery for Gentlebot.

Surfaces most-reacted content and active channels so users can
discover engaging conversations they may have missed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import asyncpg
import discord
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord import app_commands
from discord.ext import commands

from .. import bot_config as cfg
from ..util import build_db_url
from ..capabilities import CogCapabilities, CommandCapability, Category

if TYPE_CHECKING:
    pass

log = logging.getLogger(f"gentlebot.{__name__}")

LA = pytz.timezone("America/Los_Angeles")


class TrendingCog(commands.Cog):
    """Surfaces trending content and hot channels."""

    CAPABILITIES = CogCapabilities(
        commands=[
            CommandCapability(
                name="trending",
                description="/trending [hours] — See top-reacted messages and hot channels",
                category=Category.COMMUNITY,
            ),
        ]
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler: AsyncIOScheduler | None = None
        self.pool: asyncpg.Pool | None = None

    async def cog_load(self) -> None:
        url = build_db_url()
        if url:
            url = url.replace("postgresql+asyncpg://", "postgresql://")

            async def _init(conn: asyncpg.Connection) -> None:
                await conn.execute("SET search_path=discord,public")

            self.pool = await asyncpg.create_pool(url, init=_init)

        self.scheduler = AsyncIOScheduler(timezone=LA)

        # Optional scheduled daily trending post
        if cfg.TRENDING_AUTO_POST:
            trigger = CronTrigger(hour=cfg.TRENDING_AUTO_POST_HOUR, minute=0, timezone=LA)
            self.scheduler.add_job(self._auto_post_trending, trigger)
            self.scheduler.start()
            log.info(
                "TrendingCog scheduler started (auto-post at %d:00 LA)",
                cfg.TRENDING_AUTO_POST_HOUR,
            )
        else:
            log.info("TrendingCog loaded (auto-post disabled)")

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        if self.pool:
            await self.pool.close()
            self.pool = None

    # ── Data Queries ───────────────────────────────────────────────────────

    async def _get_top_reacted_messages(
        self, hours: int = 24, limit: int = 5
    ) -> list[dict]:
        """Get messages with the most reactions in the given time period.

        Returns a list of dicts with:
        - message_id, channel_id, author_id, content, created_at
        - reaction_count, channel_name, author_name
        """
        if not self.pool:
            return []

        cutoff = datetime.now(tz=LA) - timedelta(hours=hours)

        rows = await self.pool.fetch(
            """
            SELECT
                m.message_id,
                m.channel_id,
                m.author_id,
                LEFT(m.content, 150) AS content,
                m.created_at,
                c.name AS channel_name,
                u.username AS author_name,
                COUNT(DISTINCT r.event_id) AS reaction_count
            FROM discord.message m
            JOIN discord.channel c ON m.channel_id = c.channel_id
            JOIN discord."user" u ON m.author_id = u.user_id
            LEFT JOIN discord.reaction_event r
                ON r.message_id = m.message_id
                AND r.reaction_action = 'MESSAGE_REACTION_ADD'
            WHERE m.created_at >= $1
              AND c.is_private IS NOT TRUE
              AND u.is_bot IS NOT TRUE
            GROUP BY m.message_id, m.channel_id, m.author_id, m.content, m.created_at,
                     c.name, u.username
            HAVING COUNT(DISTINCT r.event_id) >= $2
            ORDER BY reaction_count DESC
            LIMIT $3
            """,
            cutoff,
            cfg.TRENDING_MIN_REACTIONS,
            limit,
        )

        return [
            {
                "message_id": r["message_id"],
                "channel_id": r["channel_id"],
                "author_id": r["author_id"],
                "content": r["content"] or "",
                "created_at": r["created_at"],
                "channel_name": r["channel_name"] or "unknown",
                "author_name": r["author_name"] or "unknown",
                "reaction_count": r["reaction_count"],
            }
            for r in rows
        ]

    async def _get_hot_channels(self, hours: int = 24, limit: int = 5) -> list[dict]:
        """Get channels with activity spikes compared to their 30-day baseline.

        Returns a list of dicts with:
        - channel_id, channel_name, recent_msgs, avg_msgs, percent_increase
        """
        if not self.pool:
            return []

        now = datetime.now(tz=LA)
        recent_cutoff = now - timedelta(hours=hours)
        baseline_cutoff = now - timedelta(days=30)

        rows = await self.pool.fetch(
            """
            WITH recent_activity AS (
                SELECT
                    m.channel_id,
                    COUNT(*) AS recent_msgs
                FROM discord.message m
                JOIN discord.channel c ON m.channel_id = c.channel_id
                WHERE m.created_at >= $1
                  AND c.is_private IS NOT TRUE
                GROUP BY m.channel_id
            ),
            baseline_activity AS (
                SELECT
                    m.channel_id,
                    COUNT(*) * 1.0 / 30 AS avg_daily_msgs
                FROM discord.message m
                JOIN discord.channel c ON m.channel_id = c.channel_id
                WHERE m.created_at >= $2
                  AND m.created_at < $1
                  AND c.is_private IS NOT TRUE
                GROUP BY m.channel_id
            )
            SELECT
                r.channel_id,
                c.name AS channel_name,
                r.recent_msgs,
                COALESCE(b.avg_daily_msgs, 0) AS avg_msgs,
                CASE
                    WHEN COALESCE(b.avg_daily_msgs, 0) = 0 THEN 0
                    ELSE ((r.recent_msgs - b.avg_daily_msgs) / b.avg_daily_msgs * 100)
                END AS percent_increase
            FROM recent_activity r
            JOIN discord.channel c ON r.channel_id = c.channel_id
            LEFT JOIN baseline_activity b ON r.channel_id = b.channel_id
            WHERE c.is_private IS NOT TRUE
              AND r.recent_msgs >= 5
              AND (
                  COALESCE(b.avg_daily_msgs, 0) = 0
                  OR (r.recent_msgs - b.avg_daily_msgs) / b.avg_daily_msgs > 0.3
              )
            ORDER BY percent_increase DESC, r.recent_msgs DESC
            LIMIT $3
            """,
            recent_cutoff,
            baseline_cutoff,
            limit,
        )

        return [
            {
                "channel_id": r["channel_id"],
                "channel_name": r["channel_name"] or "unknown",
                "recent_msgs": r["recent_msgs"],
                "avg_msgs": float(r["avg_msgs"]),
                "percent_increase": float(r["percent_increase"]),
            }
            for r in rows
        ]

    # ── Embed Building ─────────────────────────────────────────────────────

    def _build_trending_embed(
        self,
        guild: discord.Guild,
        top_messages: list[dict],
        hot_channels: list[dict],
        hours: int,
    ) -> discord.Embed:
        """Build the trending content embed."""
        embed = discord.Embed(
            title=f"\U0001f525 What's Hot ({hours}h)",
            color=discord.Color.orange(),
        )

        # Top Messages section
        if top_messages:
            msg_lines = []
            for i, msg in enumerate(top_messages[:5], 1):
                channel = guild.get_channel(msg["channel_id"])
                channel_mention = channel.mention if channel else f"#{msg['channel_name']}"

                # Build message link
                msg_link = f"https://discord.com/channels/{guild.id}/{msg['channel_id']}/{msg['message_id']}"

                # Truncate content for preview
                preview = msg["content"][:80]
                if len(msg["content"]) > 80:
                    preview += "..."

                member = guild.get_member(msg["author_id"])
                author_display = member.display_name if member else msg["author_name"]

                msg_lines.append(
                    f"{i}. [{msg['reaction_count']} reactions]({msg_link}) by **{author_display}** in {channel_mention}\n"
                    f"> {preview or '(no text)'}"
                )

            embed.add_field(
                name="\U0001f4ec Top Messages",
                value="\n\n".join(msg_lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="\U0001f4ec Top Messages",
                value="No messages with enough reactions in this period.",
                inline=False,
            )

        # Hot Channels section
        if hot_channels:
            channel_lines = []
            for ch in hot_channels[:5]:
                channel = guild.get_channel(ch["channel_id"])
                channel_mention = channel.mention if channel else f"#{ch['channel_name']}"

                if ch["percent_increase"] > 0:
                    channel_lines.append(
                        f"\U0001f4c8 {channel_mention} ({ch['recent_msgs']} msgs, +{ch['percent_increase']:.0f}% above average)"
                    )
                else:
                    channel_lines.append(
                        f"\U0001f4c8 {channel_mention} ({ch['recent_msgs']} msgs)"
                    )

            embed.add_field(
                name="\U0001f4a5 Hot Channels",
                value="\n".join(channel_lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="\U0001f4a5 Hot Channels",
                value="No channel activity spikes detected.",
                inline=False,
            )

        embed.set_footer(text="Based on public channels only")
        return embed

    # ── Auto-post ──────────────────────────────────────────────────────────

    async def _auto_post_trending(self) -> None:
        """Scheduled task to auto-post trending content."""
        await self.bot.wait_until_ready()

        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            log.error("Guild not found for trending auto-post")
            return

        channel_id = cfg.TRENDING_CHANNEL_ID or getattr(cfg, "LOBBY_CHANNEL_ID", 0)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            log.error("Trending channel %d not found or not a text channel", channel_id)
            return

        top_messages = await self._get_top_reacted_messages(hours=24, limit=5)
        hot_channels = await self._get_hot_channels(hours=24, limit=5)

        # Only post if there's meaningful content
        if not top_messages and not hot_channels:
            log.info("No trending content to post today")
            return

        embed = self._build_trending_embed(guild, top_messages, hot_channels, 24)

        try:
            await channel.send(embed=embed)
            log.info("Posted daily trending digest to channel %d", channel_id)
        except discord.HTTPException as exc:
            log.warning("Failed to post trending digest: %s", exc)

    # ── Slash Commands ─────────────────────────────────────────────────────

    @app_commands.command(name="trending", description="See what's hot right now")
    @app_commands.describe(
        hours="Time period to analyze (default: 24 hours, max: 168)",
        visibility="Whether to show publicly or just to you",
    )
    @app_commands.choices(
        visibility=[
            app_commands.Choice(name="Just me (ephemeral)", value="ephemeral"),
            app_commands.Choice(name="Public (share with channel)", value="public"),
        ]
    )
    async def trending(
        self,
        interaction: discord.Interaction,
        hours: int = 24,
        visibility: str = "ephemeral",
    ) -> None:
        """Show trending content and hot channels."""
        await interaction.response.defer(ephemeral=(visibility == "ephemeral"))

        if not self.pool:
            await interaction.followup.send("Database unavailable.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.followup.send(
                "This command only works in a server.", ephemeral=True
            )
            return

        # Clamp hours to reasonable range
        hours = max(1, min(hours, 168))  # 1 hour to 7 days

        top_messages = await self._get_top_reacted_messages(hours=hours, limit=5)
        hot_channels = await self._get_hot_channels(hours=hours, limit=5)

        embed = self._build_trending_embed(
            interaction.guild, top_messages, hot_channels, hours
        )

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrendingCog(bot))
