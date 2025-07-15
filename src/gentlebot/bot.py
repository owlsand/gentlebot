import importlib
import pkgutil
import logging
import asyncio
import discord
from discord.ext import commands
from pathlib import Path
from gentlebot.config import Settings


async def create_bot(settings: Settings) -> commands.Bot:
    intents = discord.Intents.all()
    bot = commands.Bot(command_prefix=settings.command_prefix, intents=intents)
    cog_path = Path(__file__).parent / "cogs"
    for m in pkgutil.iter_modules([str(cog_path)]):
        importlib.import_module(f"gentlebot.cogs.{m.name}")
        await bot.load_extension(f"gentlebot.cogs.{m.name}")
    logging.getLogger(__name__).info("Loaded %d cogs", len(bot.cogs))
    return bot
