import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import discord
from discord.ext import commands

import bot_config as cfg

# ─── Logging Setup ─────────────────────────────────────────────────────────
logger = logging.getLogger("gentlebot")
level_name = os.getenv("LOG_LEVEL", "INFO").upper()
level = getattr(logging, level_name, logging.INFO)
logger.setLevel(level)
log_format = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

file_handler = RotatingFileHandler("bot.log", maxBytes=1_000_000, backupCount=3)
file_handler.setFormatter(log_format)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_format)
logger.addHandler(console_handler)

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
        cog_dir = Path(__file__).parent / "cogs"
        for file in cog_dir.glob("*_cog.py"):
            await self.load_extension(f"cogs.{file.stem}")


bot = GentleBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logger.info("%s is now online in this guild", bot.user)

@bot.event
async def on_error(event: str, *args, **kwargs):
    logger.exception("Unhandled exception in event %s", event)

@bot.event
async def on_command_error(ctx: commands.Context, exc: commands.CommandError):
    logger.exception("Error in command '%s'", getattr(ctx.command, 'name', 'unknown'), exc_info=exc)

async def main():
    async with bot:
        await bot.start(cfg.TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
