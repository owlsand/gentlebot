"""Ping quiet users in the lobby when they lurk too long."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import asyncpg
import discord
from discord.ext import commands

from .. import bot_config as cfg
from ..db import get_pool
from ..infra.quotas import RateLimited
from ..llm.router import SafetyBlocked, router

log = logging.getLogger(f"gentlebot.{__name__}")


def _is_online(status: str | None) -> bool:
    """Return True when the Discord status represents being online."""

    return status not in {None, "offline", "invisible"}


class LurkerPingCog(commands.Cog):
    """Call out users who keep lurking without chatting."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.pool: asyncpg.Pool | None = None
        self.cooldown = timedelta(days=7)
        self.inactive_threshold = timedelta(days=7)
        self.transition_requirement = 2
        self._last_ping: dict[int, datetime] = {}
        self.temperature = 0.7

    async def cog_load(self) -> None:
        try:
            self.pool = await get_pool()
        except RuntimeError:
            log.warning("LurkerPingCog disabled due to missing database URL")
            self.pool = None

    async def cog_unload(self) -> None:
        self.pool = None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Reset cooldown once a user speaks up."""

        if message.guild is None or message.guild.id != getattr(cfg, "GUILD_ID", 0):
            return
        self._last_ping.pop(message.author.id, None)

    @commands.Cog.listener()
    async def on_presence_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        """Send a playful lobby ping when a lurker finally shows up online."""

        if not self.pool:
            return
        if after.guild is None or after.guild.id != getattr(cfg, "GUILD_ID", 0):
            return
        if getattr(after, "bot", False):
            return
        if getattr(after, "id", 0) == getattr(self.bot.user, "id", None):
            return
        if getattr(after, "raw_status", None) in {None, "offline"}:
            return
        if getattr(before, "raw_status", None) not in {None, "offline"}:
            return

        now = discord.utils.utcnow()
        last_ping_at = self._last_ping.get(after.id)
        if last_ping_at and now - last_ping_at < self.cooldown:
            return

        last_message_at = await self._fetch_last_message(after.id)
        if last_message_at is None:
            return
        if now - last_message_at <= self.inactive_threshold:
            return

        transitions = await self._count_online_transitions(after.id, last_message_at, now)
        if transitions < self.transition_requirement:
            return

        message = await self._build_message(after, last_message_at, transitions, now)
        if not message:
            return

        channel = self.bot.get_channel(getattr(cfg, "LOBBY_CHANNEL_ID", 0))
        if not isinstance(channel, discord.TextChannel):
            log.warning("Lobby channel %s not available", getattr(cfg, "LOBBY_CHANNEL_ID", 0))
            return

        try:
            await channel.send(message)
        except discord.HTTPException:
            log.warning("Failed to send lurker ping for user %s", after.id)
            return

        self._last_ping[after.id] = now

    async def _fetch_last_message(self, user_id: int):
        if not self.pool:
            return None
        row = await self.pool.fetchrow(
            """
            SELECT MAX(created_at) AS last_message_at
            FROM discord.message
            WHERE guild_id=$1 AND author_id=$2
            """,
            getattr(cfg, "GUILD_ID", 0),
            user_id,
        )
        return row["last_message_at"] if row else None

    async def _count_online_transitions(
        self, user_id: int, last_message_at: datetime, now: datetime
    ) -> int:
        if not self.pool:
            return 0

        previous_row = await self.pool.fetchrow(
            """
            SELECT status
            FROM discord.presence_update
            WHERE guild_id=$1 AND user_id=$2 AND event_at <= $3
            ORDER BY event_at DESC
            LIMIT 1
            """,
            getattr(cfg, "GUILD_ID", 0),
            user_id,
            last_message_at,
        )
        prev_online = _is_online(previous_row["status"]) if previous_row else False

        cutoff = now - timedelta(seconds=1)
        if cutoff <= last_message_at:
            return 0

        rows = await self.pool.fetch(
            """
            SELECT status
            FROM discord.presence_update
            WHERE guild_id=$1 AND user_id=$2
              AND event_at > $3 AND event_at < $4
            ORDER BY event_at ASC
            """,
            getattr(cfg, "GUILD_ID", 0),
            user_id,
            last_message_at,
            cutoff,
        )

        transitions = 0
        for row in rows:
            status = row["status"]
            online = _is_online(status)
            if online and not prev_online:
                transitions += 1
            prev_online = online
        return transitions

    async def _build_message(
        self,
        member: discord.Member,
        last_message_at: datetime,
        transitions: int,
        now: datetime,
    ) -> str | None:
        days = max((now - last_message_at).days, 1)
        system_prompt = (
            "You are Gentlebot, a playful yet kind Discord concierge. "
            "Compose a single message for the lobby channel calling out a quiet member. "
            "The message must warmly greet them, joke about lurking, and ask why they're so quiet. "
            "Mention the placeholder <MENTION> exactly once. Keep it under 180 characters, friendly, and safe for work."
        )
        user_prompt = (
            f"Member display name: {member.display_name}\n"
            f"Days since last message: {days}\n"
            f"Times online since then: {transitions}\n"
            "Write the final message now."
        )

        try:
            raw = await asyncio.to_thread(
                router.generate,
                "scheduled",
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                self.temperature,
            )
        except (RateLimited, SafetyBlocked) as exc:
            log.warning("scheduled lurker ping generation failed: %s", exc)
            return None
        except Exception:
            log.exception("Unexpected error generating lurker ping")
            return None

        text = (raw or "").strip()
        if not text:
            return None

        mention = member.mention
        if "<MENTION>" in text:
            text = text.replace("<MENTION>", mention)
        else:
            text = f"{mention} {text}"

        if len(text) > 1900:
            text = text[:1897] + "..."
        return text


async def setup(bot: commands.Bot) -> None:
    """Load the LurkerPingCog."""

    await bot.add_cog(LurkerPingCog(bot))
