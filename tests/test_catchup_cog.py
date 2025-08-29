import asyncio
import discord
from discord.ext import commands
from gentlebot.cogs.catchup_cog import CatchupCog
from types import SimpleNamespace


class DummyPool:
    async def fetchrow(self, query, *args):
        assert "last_seen_at" in query
        return {"last_seen_at": None}

    async def fetch(self, query, *args):
        assert "FROM discord.message" in query
        return [
            {
                "content": "hi",
                "channel_id": 1,
                "channel_name": "general",
                "display_name": "Bob",
            }
        ]


def test_catchup_command_registration(monkeypatch):
    async def run():
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = CatchupCog(bot)
        await bot.add_cog(cog)
        cmd = bot.tree.get_command("catchup")
        assert cmd is not None
        params = {p.name: p for p in cmd.parameters}
        vis = params["visibility"]
        assert vis.default == "everyone"
        assert [c.value for c in vis.choices] == ["only me", "everyone"]
        scope = params["scope"]
        assert scope.default == "all"
        assert [c.value for c in scope.choices] == ["all", "channel", "mentions"]
        style = params["style"]
        assert style.default is None
        assert style.required is False
        await bot.close()
    asyncio.run(run())


def test_collect_messages_uses_archive(monkeypatch):
    async def run():
        monkeypatch.setenv("GEMINI_API_KEY", "x")
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        cog = CatchupCog(bot)
        await bot.add_cog(cog)
        cog.pool = DummyPool()
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=1),
        )
        msgs = await cog._collect_messages(interaction, "channel")
        assert msgs == ["Bob: hi"]
        await bot.close()

    asyncio.run(run())
