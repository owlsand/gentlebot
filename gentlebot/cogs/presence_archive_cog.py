"""Archive Discord presence updates to Postgres."""
from __future__ import annotations

import json
import logging
import os

import asyncpg
import discord
from discord.ext import commands

from ..db import get_pool

log = logging.getLogger(f"gentlebot.{__name__}")


class PresenceArchiveCog(commands.Cog):
    """Persist presence update events to Postgres."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: asyncpg.Pool | None = None
        self.enabled = os.getenv("ARCHIVE_PRESENCE") == "1"

    async def cog_load(self) -> None:
        if not self.enabled:
            return
        try:
            self.pool = await get_pool()
        except RuntimeError:
            log.warning("ARCHIVE_PRESENCE set but PG_DSN is missing")
            self.enabled = False
            return
        log.info("Presence archival enabled")

    async def cog_unload(self) -> None:
        self.pool = None

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        if not self.enabled or not self.pool:
            return
        guild_id = getattr(after.guild, "id", None)
        if guild_id is None:
            return
        log.info("Presence update for %s -> %s", after.id, after.raw_status)
        activities = [getattr(a, "to_dict", lambda: {})() for a in after.activities]
        client_status = {
            k: v.value
            for k, v in {
                "desktop": after.desktop_status,
                "mobile": after.mobile_status,
                "web": after.web_status,
            }.items()
            if v and v is not discord.Status.offline
        }
        event_time = discord.utils.utcnow()
        await self.pool.execute(
            """
            INSERT INTO discord.presence_update (
                guild_id, user_id, status, activities, client_status, event_at
            )
            VALUES ($1,$2,$3,$4,$5,$6)
            """,
            guild_id,
            after.id,
            after.raw_status,
            json.dumps(activities),
            json.dumps(client_status) if client_status else None,
            event_time,
        )
        if after.raw_status != "offline":
            await self.pool.execute(
                'UPDATE discord."user" SET last_seen_at=$2 WHERE user_id=$1',
                after.id,
                event_time,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(PresenceArchiveCog(bot))
