import asyncio
from pathlib import Path
import discord
from discord.ext import commands
import bot_config as cfg

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
    print(f"[Main] {bot.user} is now online in this guild")

async def main():
    async with bot:
        await bot.start(cfg.TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
