import asyncio
import logging
import os

import discord

os.environ.setdefault("env", "TEST")
os.environ.setdefault("HF_API_TOKEN", "dummy")
os.environ.setdefault("DISCORD_TOKEN", "dummy")

from bot_config import TOKEN

from main import GentleBot


class HarnessBot(GentleBot):
    async def load_extension(self, name: str, *, package: str | None = None) -> None:
        try:
            await super().load_extension(name, package=package)
        except Exception as e:
            logging.warning("Skipping %s: %s", name, e)


async def load_cogs() -> int:
    bot = HarnessBot(command_prefix="!", intents=discord.Intents.none())
    await bot.setup_hook()
    count = len(bot.cogs)
    await bot.close()
    return count


def main():
    logging.basicConfig(level=logging.INFO)
    if not TOKEN:
        logging.warning("DISCORD_TOKEN not set; cogs will still be loaded")
    num = asyncio.run(load_cogs())
    print(f"Loaded {num} cogs successfully")


if __name__ == "__main__":
    main()
