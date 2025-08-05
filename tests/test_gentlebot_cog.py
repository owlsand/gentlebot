import asyncio
from types import SimpleNamespace

import discord
from discord.ext import commands

from gentlebot.cogs import gentlebot_cog


def test_gentlebot_sends_message():
    async def run_test():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = gentlebot_cog.GentlebotCog(bot)

        sent: list[str] = []

        async def fake_send(content: str):
            sent.append(content)

        channel = SimpleNamespace(id=1, name="chan", send=fake_send)
        user = SimpleNamespace(id=123)

        async def fake_defer(*args, **kwargs):
            pass

        async def fake_followup_send(*args, **kwargs):
            pass

        interaction = SimpleNamespace(
            user=user,
            channel=channel,
            response=SimpleNamespace(defer=fake_defer),
            followup=SimpleNamespace(send=fake_followup_send),
        )

        command = cog.gentlebot
        await command.callback(cog, interaction, say="hello world")

        assert sent == ["hello world"]
        assert command.default_permissions.administrator

    asyncio.run(run_test())
