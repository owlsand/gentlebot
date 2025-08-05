import asyncio
from types import SimpleNamespace
import discord
from discord.ext import commands

from gentlebot.cogs import burst_thread_cog


class DummyPool:
    def __init__(self):
        self.executed = []

    async def execute(self, query, *args):
        self.executed.append((query, args))

    async def close(self):
        pass


async def fake_create_pool(url, *args, **kwargs):
    assert url.startswith("postgresql://")
    return DummyPool()


def test_burst_triggers_thread(monkeypatch):
    async def run_test():
        monkeypatch.setattr(burst_thread_cog.asyncpg, "create_pool", fake_create_pool)
        monkeypatch.setenv("PG_DSN", "postgresql+asyncpg://u:p@localhost/db")
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        cog = burst_thread_cog.BurstThreadCog(bot)
        await cog.cog_load()
        pool = cog.pool

        async def fake_summary(text):
            return "Hot Sports Debate"

        monkeypatch.setattr(cog, "_summarize", fake_summary)

        async def fake_alert(topic, mention):
            return (
                f"📈 Wow, looks like you're getting pretty into {topic}! "
                f"Here's a thread if you want to take it offline to avoid blowing up "
                f"everyone else's notifications: {mention}"
            )

        monkeypatch.setattr(cog, "_alert_text", fake_alert)

        sent = []
        added = []

        class DummyThread(SimpleNamespace):
            mention = "<#1>"
            id = 1

            async def add_user(self, member):
                added.append(member.id)

        created = []

        async def fake_create_thread(name, auto_archive_duration=None):
            created.append(name)
            return DummyThread()

        class DummyChannel(SimpleNamespace):
            create_thread = staticmethod(fake_create_thread)

        channel = DummyChannel(id=10, guild=SimpleNamespace(get_member=lambda uid: SimpleNamespace(id=uid)))
        channel.send = lambda msg: sent.append(msg)
        monkeypatch.setattr(discord, "TextChannel", DummyChannel)
        base_ts = discord.utils.utcnow()
        authors = [SimpleNamespace(id=1, bot=False), SimpleNamespace(id=2, bot=False)]
        for i in range(20):
            msg = SimpleNamespace(
                channel=channel,
                author=authors[i % 2],
                created_at=base_ts,
                type=discord.MessageType.default,
                content="hi",
            )
            await cog.on_message(msg)

        assert created == ["Hot Sports Debate"]
        expected = (
            "📈 Wow, looks like you're getting pretty into hot sports debate! "
            "Here's a thread if you want to take it offline to avoid blowing up "
            "everyone else's notifications: <#1>"
        )
        assert sent == [expected]
        assert set(added) == {1, 2}
        assert pool.executed

    asyncio.run(run_test())
