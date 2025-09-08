import asyncio
import discord
from discord.ext import commands
from types import SimpleNamespace

from gentlebot.cogs import image_cog
from gentlebot.infra.quotas import RateLimited

def test_image_cog_loads(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    async def run():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        await bot.load_extension("gentlebot.cogs.image_cog")
        assert bot.get_cog("ImageCog") is not None
        await bot.close()
    asyncio.run(run())


class DummyResponse:
    def __init__(self):
        self.deferred = False

    async def defer(self, *, thinking=True):
        self.deferred = True


class DummyFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class DummyInteraction:
    def __init__(self):
        self.response = DummyResponse()
        self.followup = DummyFollowup()
        self.user = SimpleNamespace(id=1)
        self.channel = SimpleNamespace(id=1, name="chan")


def test_image_error_uses_generate(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    async def run():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        await bot.load_extension("gentlebot.cogs.image_cog")
        cog = bot.get_cog("ImageCog")

        interaction = DummyInteraction()

        def fake_generate_image(prompt):
            raise Exception("boom")

        def fake_generate(*args, **kwargs):
            return "friendly"

        monkeypatch.setattr(image_cog.router, "generate_image", fake_generate_image)
        monkeypatch.setattr(image_cog.router, "generate", fake_generate)

        await image_cog.ImageCog.image.callback(cog, interaction, prompt="hi")
        assert interaction.followup.sent[0][0] == "friendly"
        await bot.close()

    asyncio.run(run())


def test_image_error_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    async def run():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        await bot.load_extension("gentlebot.cogs.image_cog")
        cog = bot.get_cog("ImageCog")

        interaction = DummyInteraction()

        def raise_rate_limited(prompt):
            raise RateLimited()

        def fail_generate(*args, **kwargs):
            raise RateLimited()

        monkeypatch.setattr(image_cog.router, "generate_image", raise_rate_limited)
        monkeypatch.setattr(image_cog.router, "generate", fail_generate)

        await image_cog.ImageCog.image.callback(cog, interaction, prompt="hi")
        assert interaction.followup.sent[0][0] == (
            "Unfortunately I've exceeded quota and am being told to wait. Try again in a bit."
        )
        await bot.close()

    asyncio.run(run())


def test_image_includes_prompt(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    async def run():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        await bot.load_extension("gentlebot.cogs.image_cog")
        cog = bot.get_cog("ImageCog")

        interaction = DummyInteraction()

        def fake_generate_image(prompt):
            return b"img"

        monkeypatch.setattr(image_cog.router, "generate_image", fake_generate_image)

        await image_cog.ImageCog.image.callback(cog, interaction, prompt="hi")
        content, kwargs = interaction.followup.sent[0]
        assert content == "||hi||"
        assert isinstance(kwargs["file"], discord.File)
        await bot.close()

    asyncio.run(run())
