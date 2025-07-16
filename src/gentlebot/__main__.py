import asyncio
import logging
import os
import argparse
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import discord
from discord.ext import commands

import bot_config as cfg
from postgres_handler import PostgresHandler
from util import build_db_url
from version import get_version

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

class GentleBot(commands.Bot):
    async def setup_hook(self):
        # __main__ lives under src/gentlebot whereas the cogs folder sits at the
        # repository root next to main.py.  Walk one directory up to find it so
        # that loading works when running the package entry point.
        cog_dir = Path(__file__).resolve().parent.parent.parent / "cogs"
        for file in cog_dir.glob("*_cog.py"):
            if file.stem == "test_logging_cog" and not cfg.IS_TEST:
                continue
            await self.load_extension(f"cogs.{file.stem}")


bot = GentleBot(command_prefix="!", intents=intents)

_synced = False

@bot.event
async def on_ready():
    global _synced
    logger.info("%s is now online in this guild", bot.user)
    if not _synced:
        try:
            cmds = await bot.tree.sync()
            logger.info("Synced %d commands.", len(cmds))
        except Exception as e:
            logger.exception("Failed to sync commands: %s", e)
        _synced = True

@bot.event
async def on_error(event: str, *args, **kwargs):
    logger.exception("Unhandled exception in event %s", event)

@bot.event
async def on_command_error(ctx: commands.Context, exc: commands.CommandError):
    logger.exception("Error in command '%s'", getattr(ctx.command, 'name', 'unknown'), exc_info=exc)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, exc: discord.app_commands.AppCommandError):
    cmd_name = getattr(interaction.command, "name", "unknown")
    logger.exception("Error in slash command '%s'", cmd_name, exc_info=exc)
    if interaction.response.is_done():
        await interaction.followup.send("An error occurred.", ephemeral=True)
    else:
        await interaction.response.send_message("An error occurred.", ephemeral=True)

async def main():
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Gentlebot")
    parser.add_argument("--version", action="version", version=get_version())
    parser.parse_args()
    asyncio.run(main())
