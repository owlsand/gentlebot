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


@pytest.mark.asyncio
async def test_friendship_tips(monkeypatch):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = VibeCheckCog(bot)
    cur = [SimpleNamespace(content="hi", author=SimpleNamespace(display_name="a"))]
    prior = [SimpleNamespace(content="hi", author=SimpleNamespace(display_name="b"))]

    def fake_generate(route, messages, temperature, think_budget=0, json_mode=False):
        return "• tip1\n• tip2"

    monkeypatch.setattr(vibecheck_cog.router, "generate", fake_generate)

    tips = await cog._friendship_tips(cur, prior)
    await bot.close()
    assert tips == ["• tip1", "• tip2"]

