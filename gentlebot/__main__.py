"""Entry point to run the Gentlebot Discord bot."""
import asyncio
import logging
import os
import argparse
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import discord
from discord.ext import commands

from . import bot_config as cfg
from .postgres_handler import PostgresHandler
from .util import build_db_url
from .db import close_pool
from .version import get_version

# ─── Logging Setup ─────────────────────────────────────────────────────────
logger = logging.getLogger("gentlebot")
level_name = os.getenv("LOG_LEVEL", "INFO").upper()
level = getattr(logging, level_name, logging.INFO)
logger.setLevel(level)
log_format = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_format)
# Limit console output to INFO and above even when file logging is DEBUG
console_handler.setLevel(logging.INFO)

root_logger = logging.getLogger()
root_logger.setLevel(level)
root_logger.addHandler(console_handler)

logger.info(
    "Starting GentleBot in %s environment with level %s",
    getattr(cfg, "env", "PROD"),
    level_name,
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # RoleCog needs this
intents.presences = True

class GentleBot(commands.Bot):
    async def setup_hook(self) -> None:
        # Load cogs bundled with the package
        cog_dir = Path(__file__).resolve().parent / "cogs"
        for file in cog_dir.glob("*_cog.py"):
            if file.stem == "test_logging_cog" and not cfg.IS_TEST:
                continue
            await self.load_extension(f"gentlebot.cogs.{file.stem}")


bot = GentleBot(command_prefix="!", intents=intents)

_synced = False
_backfills_started = False
_backfill_tasks: list[asyncio.Task] = []

@bot.event
async def on_ready() -> None:
    global _synced, _backfills_started
    logger.info("%s is now online in this guild", bot.user)
    if not _synced:
        try:
            cmds = await bot.tree.sync()
            logger.info("Synced %d commands.", len(cmds))
            _synced = True
        except Exception as e:
            logger.exception("Failed to sync commands: %s", e)
    if not _backfills_started:
        _backfills_started = True
        days = int(os.getenv("BACKFILL_DAYS", "30"))
        from . import (
            backfill_archive,
            backfill_commands,
            backfill_reactions,
            backfill_roles,
        )

        async def _run_backfills() -> None:
            await backfill_commands.run_backfill(days)
            await asyncio.sleep(5)
            await backfill_archive.run_backfill(days)
            await asyncio.sleep(5)
            await backfill_reactions.run_backfill(days)
            await asyncio.sleep(5)
            await backfill_roles.run_backfill()

        _backfill_tasks.append(asyncio.create_task(_run_backfills()))

@bot.event
async def on_error(event: str, *args, **kwargs) -> None:
    logger.exception("Unhandled exception in event %s", event)

@bot.event
async def on_command_error(
    ctx: commands.Context, exc: commands.CommandError
) -> None:
    logger.exception("Error in command '%s'", getattr(ctx.command, 'name', 'unknown'), exc_info=exc)

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, exc: discord.app_commands.AppCommandError
) -> None:
    cmd_name = getattr(interaction.command, "name", "unknown")
    logger.exception("Error in slash command '%s'", cmd_name, exc_info=exc)
    if interaction.response.is_done():
        await interaction.followup.send("An error occurred.", ephemeral=True)
    else:
        await interaction.response.send_message("An error occurred.", ephemeral=True)

async def main() -> None:
    db_url = build_db_url()
    db_handler = None
    file_handler = None
    if db_url:
        db_handler = PostgresHandler(db_url)
        await db_handler.connect()
        root_logger.addHandler(db_handler)
        logger.info("Postgres logging enabled; file logging disabled")
    else:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            log_dir / "bot.log", when="midnight", backupCount=90
        )
        file_handler.setFormatter(log_format)
        root_logger.addHandler(file_handler)

    try:
        async with bot:
            await bot.start(cfg.TOKEN)
    finally:
        if db_handler:
            await db_handler.aclose()
        if file_handler:
            file_handler.close()
        await close_pool()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Gentlebot")
    parser.add_argument("--version", action="version", version=get_version())
    parser.parse_args()
    asyncio.run(main())
