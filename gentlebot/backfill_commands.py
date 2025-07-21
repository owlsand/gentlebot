"""Backfill command_invocations from channel history."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import timedelta

import asyncpg
import discord
from discord.ext import commands

from gentlebot import bot_config as cfg
from gentlebot.util import build_db_url

log = logging.getLogger("gentlebot.backfill_commands")


def _extract_cmd(msg: discord.Message) -> str:
    """Return slash command name from a history message."""
    return (
        getattr(getattr(msg, "interaction_metadata", None), "name", None)
        or msg.content.split()[0].lstrip("/")
    )


class BackfillBot(commands.Bot):
    def __init__(self, days: int = 90):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.days = days
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
        if self.pool:
            await self.backfill_history(self.days)
            await self.pool.close()
        await self.close()

    async def backfill_history(self, days: int) -> None:
        cutoff = discord.utils.utcnow() - timedelta(days=days)
        assert self.pool
        for guild in self.guilds:
            for channel in guild.text_channels:
                try:
                    async for msg in channel.history(limit=None, after=cutoff):
                        if msg.type is discord.MessageType.chat_input_command:
                            cmd = _extract_cmd(msg)
                            await self.pool.execute(
                                """INSERT INTO discord.command_invocations (
                                        guild_id, channel_id, user_id, command, created_at
                                    ) VALUES ($1,$2,$3,$4,$5)
                                    ON CONFLICT DO NOTHING""",
                                guild.id,
                                channel.id,
                                msg.author.id,
                                cmd,
                                msg.created_at,
                            )
                except discord.Forbidden:
                    log.warning("History fetch forbidden for %s", channel)
                except Exception as exc:  # pragma: no cover - logging only
                    log.exception("History fetch failed for %s: %s", channel, exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill command log")
    parser.add_argument(
        "--days", type=int, default=int(os.getenv("BACKFILL_DAYS", "90")), help="Number of days of history to fetch"
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    bot = BackfillBot(days=args.days)
    async with bot:
        await bot.start(cfg.TOKEN)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
