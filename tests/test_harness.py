import sys
from pathlib import Path
import asyncio
import logging
import os

os.environ.setdefault("env", "TEST")
os.environ.setdefault("HF_API_TOKEN", "dummy")
os.environ.setdefault("DISCORD_TOKEN", "dummy")
os.environ.setdefault("DATABASE_URL", "")
os.environ.pop("PG_USER", None)
os.environ.pop("PG_PASSWORD", None)
os.environ.pop("PG_DB", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gentlebot.config import settings
from gentlebot.bot import create_bot


async def load_cogs() -> int:
    bot = await create_bot(settings)
    count = len(bot.cogs)
    await bot.close()
    return count


def main():
    logging.getLogger().setLevel(logging.INFO)
    num = asyncio.run(load_cogs())
    print(f"Loaded {num} cogs successfully")


if __name__ == "__main__":
    main()
