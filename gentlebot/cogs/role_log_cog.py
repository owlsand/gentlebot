"""Record role assignments and changes to Postgres."""
from __future__ import annotations

import logging
import os

import asyncpg
import discord
from discord.ext import commands

from ..util import build_db_url

log = logging.getLogger(f"gentlebot.{__name__}")


class RoleLogCog(commands.Cog):
    """Persist role assignment events to Postgres."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: asyncpg.Pool | None = None
        self.enabled = os.getenv("LOG_ROLES") == "1"

    async def cog_load(self) -> None:
        if not self.enabled:
            return
        url = build_db_url()
        if not url:
            log.warning("LOG_ROLES set but PG_DSN is missing")
            self.enabled = False
            return
        url = url.replace("postgresql+asyncpg://", "postgresql://")

        async def _init(conn: asyncpg.Connection) -> None:
            await conn.execute("SET search_path=discord,public")

        self.pool = await asyncpg.create_pool(url, init=_init)
        log.info("Role logging enabled")

    async def cog_unload(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def _upsert_role(self, role: discord.Role | None) -> None:
        if not self.pool or role is None:
            return
        await self.pool.execute(
            """
            INSERT INTO discord.guild_role (role_id, guild_id, name, color_rgb)
            VALUES ($1,$2,$3,$4)
            ON CONFLICT (role_id) DO UPDATE SET name=$3, color_rgb=$4
            """,
            role.id,
            role.guild.id,
            role.name,
            role.color.value if role.color else None,
        )

    async def _record_assignment(self, guild_id: int, role_id: int, user_id: int) -> None:
        if not self.pool:
            return
        await self.pool.execute(
            """
            INSERT INTO discord.role_assignment (guild_id, role_id, user_id)
            VALUES ($1,$2,$3)
            ON CONFLICT DO NOTHING
            """,
            guild_id,
            role_id,
            user_id,
        )
        await self.pool.execute(
            """
            INSERT INTO discord.role_event (guild_id, role_id, user_id, action)
            VALUES ($1,$2,$3,1)
            """,
            guild_id,
            role_id,
            user_id,
        )

    async def _record_removal(self, guild_id: int, role_id: int, user_id: int) -> None:
        if not self.pool:
            return
        await self.pool.execute(
            """
            DELETE FROM discord.role_assignment
            WHERE guild_id=$1 AND role_id=$2 AND user_id=$3
            """,
            guild_id,
            role_id,
            user_id,
        )
        await self.pool.execute(
            """
            INSERT INTO discord.role_event (guild_id, role_id, user_id, action)
            VALUES ($1,$2,$3,0)
            """,
            guild_id,
            role_id,
            user_id,
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if not self.enabled or not self.pool or before.guild != after.guild:
            return
        before_ids = {r.id for r in before.roles}
        after_ids = {r.id for r in after.roles}
        added = after_ids - before_ids
        removed = before_ids - after_ids
        for rid in added:
            role = after.guild.get_role(rid)
            await self._upsert_role(role)
            await self._record_assignment(after.guild.id, rid, after.id)
        for rid in removed:
            role = before.guild.get_role(rid)
            await self._upsert_role(role)
            await self._record_removal(before.guild.id, rid, after.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleLogCog(bot))
