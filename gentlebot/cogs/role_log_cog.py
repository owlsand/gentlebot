"""Record role assignments and changes to Postgres."""
from __future__ import annotations

import logging
import json
import os

import asyncpg
import discord
from discord.ext import commands

from ..db import get_pool
from ..infra import transaction
from .. import bot_config as cfg

log = logging.getLogger(f"gentlebot.{__name__}")


class RoleLogCog(commands.Cog):
    """Persist role assignment events to Postgres."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: asyncpg.Pool | None = None
        self.enabled = os.getenv("LOG_ROLES") == "1"

    @staticmethod
    def _describe(role: discord.Role) -> str:
        """Return a string describing how the role is assigned."""
        if role.id in cfg.ROLE_DESCRIPTIONS:
            return cfg.ROLE_DESCRIPTIONS[role.id]
        if role.id in cfg.AUTO_ROLE_IDS:
            return "Assigned automatically by RolesCog"
        if getattr(role, "managed", False):
            return "Managed by integration"
        return "Manual assignment"

    async def cog_load(self) -> None:
        if not self.enabled:
            return
        try:
            self.pool = await get_pool()
        except RuntimeError:
            log.warning("LOG_ROLES set but PG_DSN is missing")
            self.enabled = False
            return
        log.info("Role logging enabled")

    async def cog_unload(self) -> None:
        self.pool = None

    async def _upsert_role(self, role: discord.Role | None) -> None:
        if not self.pool or role is None:
            return
        tag_dict = (
            {s: getattr(role.tags, s, None) for s in role.tags.__slots__}
            if role.tags is not None
            else None
        )
        tag_json = json.dumps(tag_dict) if tag_dict is not None else None
        await self.pool.execute(
            """
            INSERT INTO discord.role (
                role_id, guild_id, name, color_rgb, description,
                position, permissions, hoist, mentionable, managed,
                icon_hash, unicode_emoji, flags, tags
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            ON CONFLICT (role_id) DO UPDATE SET
                name=$3, color_rgb=$4, description=$5,
                position=$6, permissions=$7, hoist=$8,
                mentionable=$9, managed=$10, icon_hash=$11,
                unicode_emoji=$12, flags=$13, tags=$14
            """,
            role.id,
            role.guild.id,
            role.name,
            role.color.value if role.color else None,
            self._describe(role),
            role.position,
            role.permissions.value,
            role.hoist,
            role.mentionable,
            role.managed,
            getattr(role.icon, "key", None) if role.icon else None,
            role.unicode_emoji,
            role.flags.value,
            tag_json,
        )

    async def _record_assignment(self, guild_id: int, role_id: int, user_id: int) -> None:
        if not self.pool:
            return
        async with transaction(self.pool) as conn:
            await conn.execute(
                """
                INSERT INTO discord.role_assignment (guild_id, role_id, user_id)
                VALUES ($1,$2,$3)
                ON CONFLICT DO NOTHING
                """,
                guild_id,
                role_id,
                user_id,
            )
            await conn.execute(
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
        async with transaction(self.pool) as conn:
            await conn.execute(
                """
                DELETE FROM discord.role_assignment
                WHERE guild_id=$1 AND role_id=$2 AND user_id=$3
                """,
                guild_id,
                role_id,
                user_id,
            )
            await conn.execute(
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
