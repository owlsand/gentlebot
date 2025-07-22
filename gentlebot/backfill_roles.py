"""Backfill current guild roles and assignments."""
from __future__ import annotations

import asyncio
import logging

import asyncpg
import discord
from discord.ext import commands

from gentlebot import bot_config as cfg
from gentlebot.util import build_db_url

log = logging.getLogger("gentlebot.backfill_roles")


class BackfillBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.pool: asyncpg.Pool | None = None

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
                await self.pool.execute(
                    """
                    INSERT INTO discord.guild_role (role_id, guild_id, name, color_rgb)
                    VALUES ($1,$2,$3,$4)
                    ON CONFLICT (role_id) DO UPDATE SET name=$3, color_rgb=$4
                    """,
                    role.id,
                    guild.id,
                    role.name,
                    role.color.value if role.color else None,
                )
            for member in guild.members:
                for role in member.roles:
                    await self.pool.execute(
                        """
                        INSERT INTO discord.role_assignment (guild_id, role_id, user_id)
                        VALUES ($1,$2,$3)
                        ON CONFLICT DO NOTHING
                        """,
                        guild.id,
                        role.id,
                        member.id,
                    )
                    await self.pool.execute(
                        """
                        INSERT INTO discord.role_event (guild_id, role_id, user_id, action)
                        VALUES ($1,$2,$3,1)
                        """,
                        guild.id,
                        role.id,
                        member.id,
                    )
        await self.pool.close()
        await self.close()


async def main() -> None:
    bot = BackfillBot()
    async with bot:
        await bot.start(cfg.TOKEN)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
