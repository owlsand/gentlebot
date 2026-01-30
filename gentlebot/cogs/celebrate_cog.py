"""
celebrate_cog.py – /celebrate Command for Gentlebot
====================================================
User-initiated celebration feature that amplifies positive moments.

Features:
  • /celebrate @user [reason] - Send celebratory GIFs targeting a user
  • Optional LLM-generated personalized celebration message
  • Tracks celebrations in database for "most celebrated" stats
  • /celebrate_stats - Show celebration leaderboard

Configuration in bot_config.py:
  • GIPHY_API_KEY: API key for Giphy GIF service
  • CELEBRATE_LLM_ENABLED: Whether to use LLM for messages (default: True)
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
import discord
import requests
from discord import app_commands
from discord.ext import commands
from requests.adapters import HTTPAdapter, Retry

from .. import bot_config as cfg
from ..db import get_pool
from ..llm.router import router, SafetyBlocked
from ..infra import RateLimited
from ..util import user_name, chan_name
from ..capabilities import CogCapabilities, CommandCapability, Category

log = logging.getLogger(f"gentlebot.{__name__}")

# Giphy API configuration
GIPHY_API_KEY = os.getenv("GIPHY_API_KEY", "")
GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"

# Celebration search terms for variety
CELEBRATION_SEARCH_TERMS = [
    "celebrate",
    "congratulations",
    "party",
    "cheers",
    "woohoo",
    "high five",
    "applause",
    "fireworks celebration",
    "happy dance",
    "victory dance",
]

# Fallback celebration emojis if Tenor fails
CELEBRATION_EMOJIS = ["🎉", "🥳", "👏", "💪", "⭐", "🔥", "✨", "🏆", "💯", "🙌", "🎊", "🍾"]


class CelebrateCog(commands.Cog):
    """Provides the /celebrate command for community celebrations."""

    CAPABILITIES = CogCapabilities(
        commands=[
            CommandCapability(
                name="celebrate",
                description="/celebrate @user [reason] — Celebrate someone with GIFs and cheers",
                category=Category.COMMUNITY,
            ),
            CommandCapability(
                name="celebrate_stats",
                description="/celebrate_stats [days] — See the most celebrated community members",
                category=Category.COMMUNITY,
            ),
        ]
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.pool: Optional[asyncpg.Pool] = None
        self.session = self._build_session()
        self.llm_enabled = getattr(cfg, "CELEBRATE_LLM_ENABLED", True)

    def _build_session(self) -> requests.Session:
        """Build a requests session with retry logic."""
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    async def cog_load(self) -> None:
        """Initialize database connection and create tables."""
        try:
            self.pool = await get_pool()
            await self._ensure_table()
        except Exception as exc:
            self.pool = None
            log.warning("CelebrateCog disabled database persistence: %s", exc)

    async def _ensure_table(self) -> None:
        """Create the celebrations tracking table if it doesn't exist."""
        if not self.pool:
            return
        await self.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS celebrations (
                id SERIAL PRIMARY KEY,
                celebrated_user_id BIGINT NOT NULL,
                celebrated_by_user_id BIGINT NOT NULL,
                reason TEXT,
                channel_id BIGINT NOT NULL,
                message_id BIGINT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await self.pool.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_celebrations_user
            ON celebrations (celebrated_user_id)
            """
        )
        await self.pool.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_celebrations_created
            ON celebrations (created_at)
            """
        )

    def _fetch_giphy_gifs(self, search_term: str, limit: int = 5) -> List[str]:
        """Fetch GIF URLs from Giphy API."""
        if not GIPHY_API_KEY:
            log.warning("GIPHY_API_KEY not configured, skipping GIF fetch")
            return []

        try:
            resp = self.session.get(
                GIPHY_SEARCH_URL,
                params={
                    "api_key": GIPHY_API_KEY,
                    "q": search_term,
                    "limit": limit * 2,  # Fetch extra to allow for random selection
                    "rating": "pg",  # Keep it family-friendly
                },
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()

            gifs = []
            for result in data.get("data", []):
                # Get the original GIF URL - Discord will auto-embed it
                images = result.get("images", {})
                # Use downsized for smaller file size, original as fallback
                gif_data = images.get("downsized") or images.get("original")
                if gif_data:
                    url = gif_data.get("url")
                    if url:
                        gifs.append(url)

            # Shuffle and return requested number
            random.shuffle(gifs)
            return gifs[:limit]

        except Exception as exc:
            log.warning("Failed to fetch Giphy GIFs for '%s': %s", search_term, exc)
            return []

    async def _generate_celebration_message(
        self, user_name: str, reason: Optional[str], celebrator_name: str
    ) -> str:
        """Generate a personalized celebration message using LLM."""
        if not self.llm_enabled:
            return self._fallback_message(user_name, reason)

        prompt = f"""Write a brief, enthusiastic celebration message for {user_name} in a Discord server.
The message is from {celebrator_name}.
{"Reason for celebration: " + reason if reason else "No specific reason given, just a general celebration!"}

Requirements:
- Keep it to 1-2 short sentences max
- Be warm and genuine, not over-the-top
- Use 1-2 celebration emojis naturally
- Don't use @mentions, just use their name
- Match the energy of the reason if provided"""

        try:
            response = await asyncio.to_thread(
                router.generate,
                "general",
                [{"role": "user", "content": prompt}],
                temperature=0.8,
            )
            return response.strip()
        except (RateLimited, SafetyBlocked):
            log.info("LLM unavailable for celebration message, using fallback")
            return self._fallback_message(user_name, reason)
        except Exception:
            log.exception("Failed to generate celebration message")
            return self._fallback_message(user_name, reason)

    def _fallback_message(self, user_name: str, reason: Optional[str]) -> str:
        """Generate a simple fallback celebration message."""
        emojis = random.sample(CELEBRATION_EMOJIS, k=2)
        if reason:
            templates = [
                f"{emojis[0]} Big shoutout to **{user_name}** for {reason}! {emojis[1]}",
                f"{emojis[0]} Let's celebrate **{user_name}**! {reason} {emojis[1]}",
                f"{emojis[0]} Cheers to **{user_name}** — {reason}! {emojis[1]}",
            ]
        else:
            templates = [
                f"{emojis[0]} Celebrating **{user_name}**! {emojis[1]}",
                f"{emojis[0]} Big cheers for **{user_name}**! {emojis[1]}",
                f"{emojis[0]} Let's hear it for **{user_name}**! {emojis[1]}",
            ]
        return random.choice(templates)

    async def _record_celebration(
        self,
        celebrated_user_id: int,
        celebrated_by_user_id: int,
        reason: Optional[str],
        channel_id: int,
        message_id: Optional[int],
    ) -> None:
        """Record a celebration in the database."""
        if not self.pool:
            return
        try:
            await self.pool.execute(
                """
                INSERT INTO celebrations (
                    celebrated_user_id, celebrated_by_user_id, reason,
                    channel_id, message_id, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6)
                """,
                celebrated_user_id,
                celebrated_by_user_id,
                reason,
                channel_id,
                message_id,
                datetime.now(timezone.utc),
            )
        except Exception as exc:
            log.warning("Failed to record celebration: %s", exc)

    @app_commands.command(
        name="celebrate",
        description="Celebrate a community member with GIFs and cheers!"
    )
    @app_commands.describe(
        user="The person to celebrate",
        reason="What are we celebrating? (optional)",
    )
    async def celebrate(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        """Send celebratory GIFs and a message for a community member."""
        log.info(
            "/celebrate invoked by %s for %s in %s (reason: %s)",
            user_name(interaction.user),
            user_name(user),
            chan_name(interaction.channel),
            reason or "none",
        )

        await interaction.response.defer(thinking=True)

        # Don't let people celebrate bots (except for fun)
        if user.bot and user.id != self.bot.user.id:
            await interaction.followup.send(
                "Bots don't need celebrations... but I appreciate the thought! 🤖"
            )
            return

        # Pick a random celebration search term for variety
        search_term = random.choice(CELEBRATION_SEARCH_TERMS)

        # Fetch GIFs and generate message concurrently
        gif_task = asyncio.to_thread(self._fetch_giphy_gifs, search_term, 3)
        message_task = self._generate_celebration_message(
            user.display_name,
            reason,
            interaction.user.display_name,
        )

        gifs, celebration_message = await asyncio.gather(gif_task, message_task)

        # Build the response
        response_parts = [
            f"## 🎉 Celebrating {user.mention}! 🎉",
            "",
            celebration_message,
        ]

        # Add GIFs if we got them
        if gifs:
            response_parts.append("")
            for gif_url in gifs[:3]:  # Limit to 3 GIFs
                response_parts.append(gif_url)
        else:
            # No GIFs available, add extra emoji flair
            extra_emojis = " ".join(random.sample(CELEBRATION_EMOJIS, k=5))
            response_parts.append("")
            response_parts.append(extra_emojis)

        response_text = "\n".join(response_parts)

        # Send the celebration
        message = await interaction.followup.send(response_text)

        # Record the celebration in the database
        await self._record_celebration(
            celebrated_user_id=user.id,
            celebrated_by_user_id=interaction.user.id,
            reason=reason,
            channel_id=interaction.channel_id,
            message_id=message.id if message else None,
        )

    @app_commands.command(
        name="celebrate_stats",
        description="See the most celebrated members of the community!"
    )
    @app_commands.describe(
        days="Number of days to look back (default: 30)",
    )
    async def celebrate_stats(
        self,
        interaction: discord.Interaction,
        days: Optional[int] = 30,
    ) -> None:
        """Show celebration statistics and leaderboard."""
        log.info(
            "/celebrate_stats invoked by %s in %s (days: %d)",
            user_name(interaction.user),
            chan_name(interaction.channel),
            days or 30,
        )

        await interaction.response.defer(thinking=True)

        if not self.pool:
            await interaction.followup.send(
                "Celebration stats are temporarily unavailable. "
                "Try again later! 🎉"
            )
            return

        days = max(1, min(days or 30, 365))  # Clamp to 1-365 days

        try:
            # Get most celebrated users
            rows = await self.pool.fetch(
                """
                SELECT
                    celebrated_user_id,
                    COUNT(*) as celebration_count
                FROM celebrations
                WHERE created_at > now() - INTERVAL '1 day' * $1
                GROUP BY celebrated_user_id
                ORDER BY celebration_count DESC
                LIMIT 10
                """,
                days,
            )

            # Get total celebration count
            total_row = await self.pool.fetchrow(
                """
                SELECT COUNT(*) as total
                FROM celebrations
                WHERE created_at > now() - INTERVAL '1 day' * $1
                """,
                days,
            )
            total = total_row["total"] if total_row else 0

        except Exception as exc:
            log.exception("Failed to fetch celebration stats")
            await interaction.followup.send(
                "Couldn't fetch celebration stats right now. Try again later!"
            )
            return

        if not rows:
            await interaction.followup.send(
                f"No celebrations in the last {days} days. "
                f"Use `/celebrate @user` to start the party! 🎉"
            )
            return

        # Build the leaderboard
        embed = discord.Embed(
            title="🏆 Celebration Leaderboard",
            description=f"Most celebrated members in the last {days} days",
            color=discord.Color.gold(),
        )

        leaderboard_lines = []
        medals = ["🥇", "🥈", "🥉"]

        for idx, row in enumerate(rows):
            user_id = row["celebrated_user_id"]
            count = row["celebration_count"]

            # Try to get the user's display name
            member = interaction.guild.get_member(user_id) if interaction.guild else None
            name = member.display_name if member else f"User {user_id}"

            if idx < 3:
                prefix = medals[idx]
            else:
                prefix = f"**{idx + 1}.**"

            plural = "s" if count != 1 else ""
            leaderboard_lines.append(f"{prefix} {name} — {count} celebration{plural}")

        embed.add_field(
            name="Top Celebrated",
            value="\n".join(leaderboard_lines),
            inline=False,
        )

        embed.set_footer(text=f"Total celebrations: {total}")

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CelebrateCog(bot))
