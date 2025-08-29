import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

import gentlebot.cogs.gemini_cog as gemini_cog
from gentlebot.cogs.gemini_cog import GeminiCog


@asynccontextmanager
async def dummy_typing():
    yield


def test_on_message_logs_failure_no_reply(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    cog = GeminiCog(bot)
    cog.mention_strs = ["<@123>"]

    message = MagicMock(spec=discord.Message)
    message.author.bot = False
    message.author.id = 456
    message.flags = MagicMock(ephemeral=False)
    message.content = "<@123> hi"
    message.guild = None
    message.reference = None
    message.channel = MagicMock()
    message.channel.id = 789
    message.channel.typing.return_value = dummy_typing()
    message.reply = AsyncMock()

    monkeypatch.setattr(gemini_cog.random, "random", lambda: 1)

    async def raise_error(*args, **kwargs):
        raise RuntimeError("boom")

    cog.call_llm = raise_error

    asyncio.run(cog.on_message(message))

    message.reply.assert_not_called()
