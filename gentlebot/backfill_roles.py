"""Backfill current guild roles and assignments."""
from __future__ import annotations

import asyncio
import json
import logging

import asyncpg
import discord
from discord.ext import commands

from gentlebot import bot_config as cfg
from gentlebot.util import build_db_url, rows_from_tag

log = logging.getLogger("gentlebot.backfill_roles")


def role_description(role: discord.Role) -> str:
    if role.id in cfg.ROLE_DESCRIPTIONS:
        return cfg.ROLE_DESCRIPTIONS[role.id]
    if role.id in cfg.AUTO_ROLE_IDS:
        return "Assigned automatically by RolesCog"
    if role.managed:
        return "Managed by integration"
    return "Manual assignment"


class BackfillBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.pool: asyncpg.Pool | None = None
        self.counts = {
            "role": 0,
            "role_assignment": 0,
            "role_event": 0,
        }

    async def setup_hook(self) -> None:
        url = build_db_url()
        if not url:
            log.error("PG_DSN is required for backfill")
            await self.close()
            return
        url = url.replace("postgresql+asyncpg://", "postgresql://")

        async def _init(conn: asyncpg.Connection) -> None:
            await conn.execute("SET search_path=discord,public")

        self.pool = await asyncpg.create_pool(url, init=_init)

    async def on_ready(self) -> None:
        log.info("Backfill bot logged in as %s", self.user)
        assert self.pool
        for guild in self.guilds:
            for role in guild.roles:
                tag_dict = (
                    {s: getattr(role.tags, s, None) for s in role.tags.__slots__}
                    if role.tags is not None
                    else None
                )
                tag_json = json.dumps(tag_dict) if tag_dict is not None else None
                inserted = await self.pool.fetchval(
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
                    RETURNING xmax = 0
                    """,
                    role.id,
                    guild.id,
                    role.name,
                    role.color.value if role.color else None,
                    role_description(role),
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
                self.counts["role"] += int(bool(inserted))
            for member in guild.members:
                for role in member.roles:
                    tag = await self.pool.execute(
                        """
                        INSERT INTO discord.role_assignment (guild_id, role_id, user_id)
                        VALUES ($1,$2,$3)
                        ON CONFLICT DO NOTHING
                        """,
                        guild.id,
                        role.id,
                        member.id,
                    )
                    self.counts["role_assignment"] += rows_from_tag(tag)
                    tag = await self.pool.execute(
                        """
                        INSERT INTO discord.role_event (guild_id, role_id, user_id, action)
                        VALUES ($1,$2,$3,1)
                        """,
                        guild.id,
                        role.id,
                        member.id,
                    )
                    self.counts["role_event"] += rows_from_tag(tag)
        await self.pool.close()
        log.info(
            "Inserted %d roles, %d assignments, %d events",
            self.counts["role"],
            self.counts["role_assignment"],
            self.counts["role_event"],
        )
        await self.close()


async def run_backfill() -> None:
    """Run the role backfill."""
    bot = BackfillBot()
    async with bot:
        await bot.start(cfg.TOKEN)


async def main() -> None:
    await run_backfill()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
