from gentlebot.config import settings
from gentlebot.logging_config import configure_logging
from gentlebot.bot import create_bot
import asyncio

async def main():
    configure_logging()
    bot = await create_bot(settings)
    await bot.start(settings.discord_token)

if __name__ == "__main__":
    asyncio.run(main())
