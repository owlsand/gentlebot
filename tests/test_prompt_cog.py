import types
import asyncio
from gentlebot.cogs import prompt_cog


def test_engagement_bait_category_and_fallback(monkeypatch):
    assert "Engagement Bait" in prompt_cog.PROMPT_CATEGORIES

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(prompt_cog, "FALLBACK_PROMPTS", ["React with an emoji!"])
    monkeypatch.setattr(prompt_cog.router, "generate", lambda *a, **k: (_ for _ in ()).throw(Exception("boom")))

    def fake_choice(seq):
        if seq == prompt_cog.PROMPT_CATEGORIES:
            return "Engagement Bait"
        return seq[0]

    monkeypatch.setattr(prompt_cog.random, "choice", fake_choice)

    cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())
    prompt = asyncio.run(cog.fetch_prompt())
    assert prompt == "React with an emoji!"
    assert cog.last_category == "Engagement Bait"


def test_sports_news_category_and_fallback(monkeypatch):
    assert "Sports News" in prompt_cog.PROMPT_CATEGORIES

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(prompt_cog, "FALLBACK_PROMPTS", ["Goal or no goal?"])
    monkeypatch.setattr(prompt_cog.router, "generate", lambda *a, **k: (_ for _ in ()).throw(Exception("boom")))

    async def fake_topic(self):
        return "Team X wins"

    monkeypatch.setattr(prompt_cog.PromptCog, "_sports_news_topic", fake_topic)

    def fake_choice(seq):
        if seq == prompt_cog.PROMPT_CATEGORIES:
            return "Sports News"
        return seq[0]

    monkeypatch.setattr(prompt_cog.random, "choice", fake_choice)

    cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())
    prompt = asyncio.run(cog.fetch_prompt())
    assert prompt == "Goal or no goal?"
    assert cog.last_category == "Sports News"


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
    monkeypatch.setenv("GEMINI_API_KEY", "token")
    monkeypatch.setattr(prompt_cog.router, "generate", lambda *a, **k: '"Quoted prompt"')
    monkeypatch.setattr(prompt_cog.random, "choice", lambda seq: seq[0])

    cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())
    prompt = asyncio.run(cog.fetch_prompt())
    assert prompt == "Quoted prompt"
    assert not prompt.startswith('"') and not prompt.endswith('"')


def test_send_prompt_posts_message(monkeypatch):
    async def run():
        monkeypatch.setattr(prompt_cog.cfg, "DAILY_PING_CHANNEL", 123)

        class DummyChannel:
            def __init__(self):
                self.sent = None
                self.id = 123

            async def send(self, content):
                self.sent = content
                return types.SimpleNamespace(id=456, channel=self)

            async def create_thread(self, *args, **kwargs):  # pragma: no cover - should not be called
                raise AssertionError("create_thread should not be used")

        channel = DummyChannel()
        bot = types.SimpleNamespace(get_channel=lambda _id: channel)
        cog = prompt_cog.PromptCog(bot)

        async def fake_fetch_prompt(self):
            self.last_category = "cat"
            return "hello"

        async def fake_archive(self, *args):
            pass

        monkeypatch.setattr(prompt_cog.PromptCog, "fetch_prompt", fake_fetch_prompt)
        monkeypatch.setattr(prompt_cog.PromptCog, "_archive_prompt", fake_archive)

        await cog._send_prompt()
        assert channel.sent == "hello"

    asyncio.run(run())


def test_send_prompt_handles_long_message(monkeypatch):
    async def run():
        monkeypatch.setattr(prompt_cog.cfg, "DAILY_PING_CHANNEL", 123)

        class DummyChannel:
            def __init__(self):
                self.sent = None
                self.id = 123

            async def send(self, content):
                self.sent = content
                return types.SimpleNamespace(id=456, channel=self)

            async def create_thread(self, *args, **kwargs):  # pragma: no cover - should not be called
                raise AssertionError("create_thread should not be used")

        long_prompt = "A" * 200
        channel = DummyChannel()
        bot = types.SimpleNamespace(get_channel=lambda _id: channel)
        cog = prompt_cog.PromptCog(bot)

        async def fake_fetch_prompt(self):
            self.last_category = "cat"
            return long_prompt

        async def fake_archive(self, *args):
            pass

        monkeypatch.setattr(prompt_cog.PromptCog, "fetch_prompt", fake_fetch_prompt)
        monkeypatch.setattr(prompt_cog.PromptCog, "_archive_prompt", fake_archive)

        await cog._send_prompt()
        assert channel.sent == long_prompt

    asyncio.run(run())


def test_send_prompt_archives_channel_id(monkeypatch):
    async def run():
        monkeypatch.setattr(prompt_cog.cfg, "DAILY_PING_CHANNEL", 123)

        class DummyChannel:
            def __init__(self):
                self.id = 123

            async def send(self, content):
                return types.SimpleNamespace(id=456, channel=self)

        channel = DummyChannel()
        bot = types.SimpleNamespace(get_channel=lambda _id: channel)
        cog = prompt_cog.PromptCog(bot)

        async def fake_fetch_prompt(self):
            self.last_category = "cat"
            return "hi"

        captured = {}

        async def fake_archive(self, prompt, category, channel_id, topic=None):
            captured["channel_id"] = channel_id

        monkeypatch.setattr(prompt_cog.PromptCog, "fetch_prompt", fake_fetch_prompt)
        monkeypatch.setattr(prompt_cog.PromptCog, "_archive_prompt", fake_archive)

        await cog._send_prompt()
        assert captured["channel_id"] == 123

    asyncio.run(run())

