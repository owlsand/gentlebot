import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

from gentlebot.cogs import ambient_image_cog


def test_ambient_image_cog_loads(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    async def run():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        await bot.load_extension("gentlebot.cogs.ambient_image_cog")
        assert bot.get_cog("AmbientImageCog") is not None
        await bot.close()

    asyncio.run(run())


def test_ambient_image_cog_triggers(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    cog = ambient_image_cog.AmbientImageCog(bot)

    message = MagicMock(spec=discord.Message)
    message.author.bot = False
    message.flags = MagicMock(ephemeral=False)
    message.channel = MagicMock()
    message.channel.send = AsyncMock()

    history_messages = []
    for i in range(20):
        m = MagicMock(spec=discord.Message)
        m.author.bot = False
        m.content = f"msg{i}"
        history_messages.append(m)

    async def fake_history(limit):
        for m in history_messages:
            yield m

    message.channel.history.side_effect = fake_history

    monkeypatch.setattr(ambient_image_cog.random, "random", lambda: 0)

    captured = {}

    def fake_generate(route, messages, *args, **kwargs):
        captured["messages"] = messages
        return "final prompt"

    def fake_generate_image(prompt: str):
        captured["prompt"] = prompt
        return b"img"

    monkeypatch.setattr(ambient_image_cog.router, "generate", fake_generate)
    monkeypatch.setattr(ambient_image_cog.router, "generate_image", fake_generate_image)

    asyncio.run(cog.on_message(message))

    assert "msg0" in captured["messages"][0]["content"]
    assert captured["prompt"] == "final prompt"
    message.channel.send.assert_called_once()
