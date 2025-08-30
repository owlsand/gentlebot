"""One-off utility to backfill message history into archive tables."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import timedelta

import discord
from discord.ext import commands

from gentlebot import bot_config as cfg
from gentlebot.cogs.message_archive_cog import MessageArchiveCog
from gentlebot.util import chan_name

log = logging.getLogger("gentlebot.backfill")


class BackfillBot(commands.Bot):
    def __init__(self, days: int = 30):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.archive = MessageArchiveCog(self)
        self.days = days
        self.counts = {
            "guild": 0,
            "channel": 0,
            "user": 0,
            "message": 0,
            "attachment": 0,
        }

    async def setup_hook(self) -> None:
        await self.archive.cog_load()

    async def on_ready(self) -> None:
        log.info("Backfill bot logged in as %s", self.user)
        await self.backfill_history(self.days)
        log.info(
            "Inserted %d guilds, %d channels, %d users, %d messages, %d attachments",
            self.counts["guild"],
            self.counts["channel"],
            self.counts["user"],
            self.counts["message"],
            self.counts["attachment"],
        )
        await self.archive.cog_unload()
        await self.close()

    async def backfill_history(self, days: int) -> None:
        if not self.archive.enabled or not self.archive.pool:
            log.error("Archive cog is disabled; check environment variables")
            return
        cutoff = discord.utils.utcnow() - timedelta(days=days)
        for guild in self.guilds:
            try:
                self.counts["guild"] += await self.archive._upsert_guild(guild)
            except Exception as exc:
                log.exception("Failed to record guild %s: %s", guild.name, exc)
                continue
            for channel in guild.text_channels:
                try:
                    self.counts["channel"] += await self.archive._upsert_channel(channel)
                except Exception as exc:
                    log.exception(
                        "Failed to record channel %s: %s", chan_name(channel), exc
                    )
                    continue
                try:
                    async for msg in channel.history(limit=None, after=cutoff):
                        try:
                            self.counts["user"] += await self.archive._upsert_user(msg.author)
                            msg_count, att_count = await self.archive._insert_message(msg)
                            self.counts["message"] += msg_count
                            self.counts["attachment"] += att_count
                        except Exception as msg_exc:
                            log.exception("Failed to record message %s: %s", msg.id, msg_exc)
                except discord.Forbidden as exc:
                      log.warning(
                          "History fetch failed for channel %s: %s",
                          chan_name(channel),
                          exc,
                      )
                except Exception as exc:  # pragma: no cover - best effort logging
                      log.exception(
                          "History fetch failed for channel %s: %s",
                          chan_name(channel),
                          exc,
                      )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill archival tables")
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.getenv("BACKFILL_DAYS", "30")),
        help="Number of days of history to fetch",
    )
    return parser.parse_args()


async def run_backfill(days: int) -> None:
    """Run the archive backfill for the given number of days."""
    bot = BackfillBot(days=days)
    async with bot:
        await bot.start(cfg.TOKEN)


async def main() -> None:
    args = parse_args()
    await run_backfill(args.days)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
