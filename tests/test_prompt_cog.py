import types
import asyncio
from gentlebot.cogs import prompt_cog


def test_engagement_bait_category_and_fallback(monkeypatch):
    assert "Engagement Bait" in prompt_cog.PROMPT_CATEGORIES

    monkeypatch.setenv("HF_API_TOKEN", "")
    monkeypatch.setattr(prompt_cog, "FALLBACK_PROMPTS", ["React with an emoji!"])

    def fake_choice(seq):
        if seq == prompt_cog.PROMPT_CATEGORIES:
            return "Engagement Bait"
        return seq[0]

    monkeypatch.setattr(prompt_cog.random, "choice", fake_choice)

    cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())
    prompt = asyncio.run(cog.fetch_prompt())
    assert prompt == "React with an emoji!"
    assert cog.last_category == "Engagement Bait"


def test_archive_prompt_missing_table():
    async def run():
        cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())

        class DummyPool:
            async def execute(self, *args):
                raise prompt_cog.asyncpg.UndefinedTableError("msg", "detail", "hint")

        cog.pool = DummyPool()
        await cog._archive_prompt("hi", "cat", 1)

    asyncio.run(run())


def test_archive_prompt_uses_schema():
    async def run():
        cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())

        captured = {}

        class DummyPool:
            async def execute(self, query, *args):
                captured['query'] = query

        cog.pool = DummyPool()
        await cog._archive_prompt('hi', 'cat', 1)

        assert 'discord.daily_prompt' in captured['query']

    asyncio.run(run())


def test_on_message_missing_table():
    async def run():
        bot = types.SimpleNamespace()
        cog = prompt_cog.PromptCog(bot)

        class DummyPool:
            async def fetchrow(self, *args):
                raise prompt_cog.asyncpg.UndefinedTableError("msg", "detail", "hint")

            async def execute(self, *args):  # pragma: no cover - shouldn't be called
                raise AssertionError("execute should not be called")

        cog.pool = DummyPool()
        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=1),
        )
        await cog.on_message(msg)

    asyncio.run(run())


def test_on_message_uses_schema():
    async def run():
        bot = types.SimpleNamespace()
        cog = prompt_cog.PromptCog(bot)

        captured = []

        class DummyPool:
            async def fetchrow(self, query, *args):
                captured.append(query)
                return None

        cog.pool = DummyPool()
        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=1),
        )
        await cog.on_message(msg)

        assert 'discord.daily_prompt' in captured[0]

    asyncio.run(run())
