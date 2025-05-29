import asyncio, discord
from discord.ext import commands
import bot_config as cfg

intents = discord.Intents.default()
intents.message_content = True
intents.members         = True          # RoleCog needs this

bot = commands.Bot(command_prefix="!", intents=intents)

async def load_cogs():
    await bot.load_extension("f1_cog")
    await bot.load_extension("market_cog")
    await bot.load_extension("roles_cog")
    await bot.load_extension("prompt_cog")

@bot.event
async def on_ready():
    print(f"[Main] {bot.user} is now online in this guild")

async def main():
    async with bot:
        await load_cogs()
        await bot.start(cfg.TOKEN)

if __name__ == "__main__":
    asyncio.run(main())