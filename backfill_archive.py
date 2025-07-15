from __future__ import annotations
"""One-off utility to backfill message history into archive tables."""

import argparse
import asyncio
import logging
from datetime import timedelta

import discord
from discord.ext import commands

import bot_config as cfg
from cogs.message_archive_cog import MessageArchiveCog

log = logging.getLogger("gentlebot.backfill")


class BackfillBot(commands.Bot):
    def __init__(self, days: int = 90):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.archive = MessageArchiveCog(self)
        self.days = days

    async def setup_hook(self) -> None:
        await self.archive.cog_load()

    async def on_ready(self) -> None:
        log.info("Backfill bot logged in as %s", self.user)
        await self.backfill_history(self.days)
        await self.archive.cog_unload()
        await self.close()

    async def backfill_history(self, days: int) -> None:
        if not self.archive.enabled or not self.archive.pool:
            log.error("Archive cog is disabled; check environment variables")
            return
        cutoff = discord.utils.utcnow() - timedelta(days=days)
        for guild in self.guilds:
            try:
                await self.archive._upsert_guild(guild)
            except Exception as exc:
                log.exception("Failed to record guild %s: %s", guild.name, exc)
                continue
            for channel in guild.text_channels:
                try:
                    await self.archive._upsert_channel(channel)
                except Exception as exc:
                    log.exception("Failed to record channel %s: %s", channel.name, exc)
                    continue
                try:
                    async for msg in channel.history(limit=None, after=cutoff):
                        try:
                            await self.archive._upsert_user(msg.author)
                            await self.archive._insert_message(msg)
                        except Exception as msg_exc:
                            log.exception("Failed to record message %s: %s", msg.id, msg_exc)
                except discord.Forbidden as exc:
                    log.warning("History fetch failed for channel %s: %s", channel.name, exc)
                except Exception as exc:  # pragma: no cover - best effort logging
                    log.exception("History fetch failed for channel %s: %s", channel.name, exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill archival tables")
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days of history to fetch",
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
