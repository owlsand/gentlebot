import asyncio
import pytest
import discord
from types import SimpleNamespace
from discord.ext import commands

from gentlebot.cogs import vibecheck_cog
from gentlebot.cogs.vibecheck_cog import z_to_bar, VibeCheckCog


@pytest.mark.parametrize(
    "z,bar",
    [
        (-3.0, "▁"),
        (-1.5, "▂"),
        (0.0, "▄"),
        (1.0, "▅"),
        (2.6, "▇"),
    ],
)
def test_z_to_bar(z, bar):
    assert z_to_bar(z) == bar


def test_friendship_tips(monkeypatch):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)
    cur = [SimpleNamespace(content="hi", author=SimpleNamespace(display_name="a"))]
    prior = [SimpleNamespace(content="hi", author=SimpleNamespace(display_name="b"))]

    def fake_generate(route, messages, temperature, think_budget=0, json_mode=False):
        return "• tip1\n• tip2"

    monkeypatch.setattr(vibecheck_cog.router, "generate", fake_generate)

    async def run():
        tips = await cog._friendship_tips(cur, prior)
        await bot.close()
        return tips

    tips = asyncio.run(run())
    assert tips == ["• tip1", "• tip2"]


def test_vibecheck_defers(monkeypatch):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)
    cog.pool = object()

    async def fake_gather(start, end):
        return []

    async def fake_tips(cur, prior):
        return ["• tip"]

    monkeypatch.setattr(cog, "_gather_messages", fake_gather)
    monkeypatch.setattr(cog, "_friendship_tips", fake_tips)

    class DummyResponse:
        def __init__(self):
            self.deferred = False
            self.kw = None

        async def defer(self, **kwargs):
            self.deferred = True
            self.kw = kwargs

    class DummyFollowup:
        def __init__(self):
            self.sent = None

        async def send(self, content, **kwargs):
            self.sent = (content, kwargs)

    interaction = SimpleNamespace(
        user=SimpleNamespace(display_name="u", id=1),
        channel=SimpleNamespace(name="c"),
        response=DummyResponse(),
        followup=DummyFollowup(),
    )

    async def run():
        await VibeCheckCog.vibecheck.callback(cog, interaction)
        await bot.close()

    asyncio.run(run())

    assert interaction.response.deferred is True
    assert interaction.followup.sent is not None
    assert interaction.followup.sent[1].get("ephemeral") is True

