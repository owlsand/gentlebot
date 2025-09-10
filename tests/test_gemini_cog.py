import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands
import logging

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


def test_on_message_no_ambient_reply(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    cog = GeminiCog(bot)
    cog.mention_strs = ["<@123>"]

    message = MagicMock(spec=discord.Message)
    message.author.bot = False
    message.author.id = 456
    message.flags = MagicMock(ephemeral=False)
    message.content = "hello world"
    message.guild = None
    message.reference = None
    message.channel = MagicMock()
    message.channel.id = 789
    message.channel.typing.return_value = dummy_typing()
    message.reply = AsyncMock()
    message.add_reaction = AsyncMock()

    monkeypatch.setattr(gemini_cog.random, "random", lambda: 0)

    asyncio.run(cog.on_message(message))

    message.reply.assert_not_called()
    message.add_reaction.assert_called_once()


def test_call_llm_robot_persona(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    cog = GeminiCog(bot)

    captured: dict[str, list[dict]] = {}

    def fake_generate(route: str, messages: list[dict], temperature: float):
        captured["messages"] = messages
        return "hi"

    monkeypatch.setattr(gemini_cog.router, "generate", fake_generate)

    asyncio.run(cog.call_llm(0, "hello"))

    system_msg = next(m for m in captured["messages"] if m["role"] == "system")
    assert system_msg["content"] == (
        "Speak like a helpful and concise robot interacting with a Discord server of friends."
    )


def test_call_llm_logs_output_not_input(monkeypatch, caplog):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    cog = GeminiCog(bot)

    def fake_generate(route: str, messages: list[dict], temperature: float):
        return "logged output"

    monkeypatch.setattr(gemini_cog.router, "generate", fake_generate)

    with caplog.at_level(logging.INFO):
        asyncio.run(cog.call_llm(0, "secret input"))

    assert "secret input" not in caplog.text
    assert "logged output" in caplog.text


def test_choose_emoji_llm_custom_and_standard(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    cog = GeminiCog(bot)

    async def fake_custom(_cid: int, _prompt: str) -> str:
        return "<:party:123>"

    cog.call_llm = fake_custom
    result = asyncio.run(cog.choose_emoji_llm("hello", ["<:party:123>"]))
    assert result == "<:party:123>"

    async def fake_standard(_cid: int, _prompt: str) -> str:
        return "🔥"

    cog.call_llm = fake_standard
    result = asyncio.run(cog.choose_emoji_llm("hello", []))
    assert result == "🔥"


def test_on_message_includes_archive_context(monkeypatch):
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

    captured: dict[str, str] = {}

    async def fake_call(cid: int, prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    async def fake_context(_cid: int) -> str:
        return "Alice: hello\nBob: hey"

    cog.call_llm = fake_call
    cog._get_context_from_archive = fake_context

    asyncio.run(cog.on_message(message))

    assert "Alice: hello" in captured["prompt"]
    assert "User message: hi" in captured["prompt"]
    message.reply.assert_called_once_with("ok")


def test_on_message_context_sanitization(monkeypatch):
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

    captured: dict[str, str] = {}

    async def fake_call(cid: int, prompt: str) -> str:
        captured["prompt"] = prompt
        return "ok"

    async def fake_context(_cid: int) -> str:
        return "Role shout <@&5>!" + ("x" * 800)

    cog.call_llm = fake_call
    cog._get_context_from_archive = fake_context

    asyncio.run(cog.on_message(message))

    assert "<@&5>" not in captured["prompt"]
    assert len(captured["prompt"]) <= cog.MAX_PROMPT_LEN
    message.reply.assert_called_once_with("ok")
