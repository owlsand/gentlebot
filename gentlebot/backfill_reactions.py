"""Backfill reaction events for historical messages."""
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
from gentlebot.util import build_db_url, chan_name, rows_from_tag, ReactionAction

log = logging.getLogger("gentlebot.backfill_reactions")


class BackfillBot(commands.Bot):
    def __init__(self, days: int = 30):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.days = days
        self.pool: asyncpg.Pool | None = None
        self.inserted = 0

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
        await self.backfill_history(self.days)
        log.info("Inserted %d reaction_event records", self.inserted)
        await self.pool.close()
        await self.close()

    async def backfill_history(self, days: int) -> None:
        cutoff = discord.utils.utcnow() - timedelta(days=days)
        assert self.pool
        for guild in self.guilds:
            for channel in guild.text_channels:
                try:
                    async for msg in channel.history(limit=None, after=cutoff):
                        for reaction in msg.reactions:
                            try:
                                users = [u async for u in reaction.users(limit=None)]
                            except Exception as exc:  # pragma: no cover - best effort
                                log.exception(
                                    "Reaction fetch failed for %s on %s: %s",
                                    reaction.emoji,
                                    msg.id,
                                    exc,
                                )
                                continue
                            for user in users:
                                if user.bot:
                                    continue
                                tag = await self.pool.execute(
                                    """
                                    INSERT INTO discord.reaction_event (
                                        message_id, user_id, emoji, reaction_action, event_at
                                    ) VALUES ($1,$2,$3,$4,$5)
                                    ON CONFLICT ON CONSTRAINT uniq_reaction_event_msg_user_emoji_act_ts DO NOTHING
                                    """,
                                    msg.id,
                                    user.id,
                                    str(reaction.emoji),
                                    ReactionAction.MESSAGE_REACTION_ADD.name,
                                    msg.created_at,
                                )
                                self.inserted += rows_from_tag(tag)
                except discord.Forbidden as exc:
                    log.warning(
                        "History fetch forbidden for channel %s: %s",
                        chan_name(channel),
                        exc,
                    )
                except Exception as exc:  # pragma: no cover - best effort
                    log.exception(
                        "History fetch failed for channel %s: %s",
                        chan_name(channel),
                        exc,
                    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill reaction events")
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.getenv("BACKFILL_DAYS", "30")),
        help="Number of days of history to fetch",
    )
    return parser.parse_args(argv)


async def main() -> None:
    args = parse_args()
    bot = BackfillBot(days=args.days)
    async with bot:
        await bot.start(cfg.TOKEN)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
