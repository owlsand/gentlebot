import asyncio
import discord
from discord.ext import commands

def test_image_cog_loads(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    async def run():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        await bot.load_extension("gentlebot.cogs.image_cog")
        assert bot.get_cog("ImageCog") is not None
        await bot.close()
    asyncio.run(run())
