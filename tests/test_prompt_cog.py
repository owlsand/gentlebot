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


def test_current_event_category_removed():
    assert "Current event" not in prompt_cog.PROMPT_CATEGORIES


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


def test_duplicate_prompt_updates_message_count():
    async def run():
        bot = types.SimpleNamespace()
        cog = prompt_cog.PromptCog(bot)

        class DummyPool:
            def __init__(self):
                self.rows = {}

            async def execute(self, query, *args):
                query = query.strip()
                if query.startswith("INSERT INTO discord.daily_prompt"):
                    prompt, category, thread_id, topic = args
                    self.rows[prompt] = {
                        "category": category,
                        "thread_id": thread_id,
                        "message_count": 0,
                        "topic": topic,
                    }
                elif query.startswith("UPDATE discord.daily_prompt SET message_count"):
                    (thread_id,) = args
                    for row in self.rows.values():
                        if row["thread_id"] == thread_id:
                            row["message_count"] += 1

            async def fetchrow(self, query, thread_id):
                for row in self.rows.values():
                    if row["thread_id"] == thread_id:
                        return object()
                return None

        pool = DummyPool()
        cog.pool = pool

        await cog._archive_prompt("hi", "cat", 1)
        await cog._archive_prompt("hi", "cat", 2)

        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=2),
        )
        await cog.on_message(msg)

        assert pool.rows["hi"]["message_count"] == 1

    asyncio.run(run())


def test_fetch_prompt_strips_outer_quotes(monkeypatch):
    monkeypatch.setenv("HF_API_TOKEN", "token")

    class DummyInferenceClient:
        def __init__(self, provider, api_key):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=None)
            )

    async def fake_to_thread(func, *args, **kwargs):
        msg = types.SimpleNamespace(content='"Quoted prompt"')
        completion = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=msg)]
        )
        return completion

    monkeypatch.setattr(prompt_cog, "InferenceClient", DummyInferenceClient)
    monkeypatch.setattr(prompt_cog.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(prompt_cog.random, "choice", lambda seq: seq[0])

    cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())
    prompt = asyncio.run(cog.fetch_prompt())
    assert prompt == "Quoted prompt"
    assert not prompt.startswith('"') and not prompt.endswith('"')

