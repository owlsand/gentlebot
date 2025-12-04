import types
import asyncio
from gentlebot.cogs import prompt_cog


def test_learning_explainer_category_and_fallback(monkeypatch):
    assert "Learning Explainer" in prompt_cog.PROMPT_CATEGORIES

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(prompt_cog, "FALLBACK_PROMPTS", ["Share a quick explainer!"])
    monkeypatch.setattr(prompt_cog.router, "generate", lambda *a, **k: (_ for _ in ()).throw(Exception("boom")))

    def fake_choice(seq):
        if seq == prompt_cog.PROMPT_CATEGORIES:
            return "Learning Explainer"
        return seq[0]

    monkeypatch.setattr(prompt_cog.random, "choice", fake_choice)

    cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())
    prompt = asyncio.run(cog.fetch_prompt())
    assert prompt == "Share a quick explainer!"
    assert cog.last_category == "Learning Explainer"


def test_current_events_category_and_fallback(monkeypatch):
    assert "Current Events" in prompt_cog.PROMPT_CATEGORIES

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(prompt_cog, "FALLBACK_PROMPTS", ["What's a headline we should unpack?"])
    monkeypatch.setattr(prompt_cog.router, "generate", lambda *a, **k: (_ for _ in ()).throw(Exception("boom")))

    async def fake_topic(self):
        return "Inclusive policy is proposed"

    monkeypatch.setattr(prompt_cog.PromptCog, "_current_events_topic", fake_topic)

    def fake_choice(seq):
        if seq == prompt_cog.PROMPT_CATEGORIES:
            return "Current Events"
        return seq[0]

    monkeypatch.setattr(prompt_cog.random, "choice", fake_choice)

    cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())
    prompt = asyncio.run(cog.fetch_prompt())
    assert prompt == "What's a headline we should unpack?"
    assert cog.last_category == "Current Events"


def test_old_categories_removed():
    assert "Engagement Bait" not in prompt_cog.PROMPT_CATEGORIES
    assert "Sports News" not in prompt_cog.PROMPT_CATEGORIES


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
            async def execute(self, *args):
                raise prompt_cog.asyncpg.UndefinedTableError("msg", "detail", "hint")

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
            async def execute(self, query, *args):
                captured.append(query)

        cog.pool = DummyPool()
        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=1),
        )
        await cog.on_message(msg)

        assert 'discord.daily_prompt' in captured[0]

    asyncio.run(run())


def test_recent_server_topic_uses_schema(monkeypatch):
    async def run():
        cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())

        captured = {}

        class DummyPool:
            async def fetch(self, query, *args):
                captured['query'] = query
                return [{"content": "hi"}]

        cog.pool = DummyPool()
        monkeypatch.setattr(prompt_cog.router, "generate", lambda *a, **k: "topic")

        topic = await cog._recent_server_topic()

        assert 'FROM discord.message' in captured['query']
        assert 'JOIN discord."user"' in captured['query']
        assert 'JOIN discord.channel' in captured['query']
        assert topic == 'topic'

    asyncio.run(run())


def test_duplicate_prompt_updates_message_count():
    async def run():
        bot = types.SimpleNamespace()
        cog = prompt_cog.PromptCog(bot)

        class DummyPool:
            def __init__(self):
                self.rows = {}
                self.next_id = 1

            async def execute(self, query, *args):
                query = query.strip()
                if query.startswith("INSERT INTO discord.daily_prompt"):
                    prompt, category, channel_id, topic = args
                    now = prompt_cog.datetime.now(prompt_cog.ZoneInfo("UTC"))
                    row = self.rows.get(prompt)
                    if row:
                        row.update(
                            {
                                "category": category,
                                "channel_id": channel_id,
                                "message_count": 0,
                                "topic": topic,
                                "created_at": now,
                            }
                        )
                    else:
                        self.rows[prompt] = {
                            "id": self.next_id,
                            "category": category,
                            "channel_id": channel_id,
                            "message_count": 0,
                            "topic": topic,
                            "created_at": now,
                        }
                        self.next_id += 1
                elif query.startswith("UPDATE discord.daily_prompt"):
                    channel_id, start, end = args
                    for row in self.rows.values():
                        if row["channel_id"] == channel_id and start <= row["created_at"] < end:
                            row["message_count"] += 1

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

def test_on_message_updates_all_today_prompts():
    async def run():
        bot = types.SimpleNamespace()
        cog = prompt_cog.PromptCog(bot)

        class DummyPool:
            def __init__(self):
                self.rows = {}
                self.next_id = 1

            async def execute(self, query, *args):
                query = query.strip()
                if query.startswith("INSERT INTO discord.daily_prompt"):
                    prompt, category, channel_id, topic = args
                    now = prompt_cog.datetime.now(prompt_cog.ZoneInfo("UTC"))
                    self.rows[prompt] = {
                        "id": self.next_id,
                        "prompt": prompt,
                        "channel_id": channel_id,
                        "message_count": 0,
                        "created_at": now,
                        "topic": topic,
                    }
                    self.next_id += 1
                elif query.startswith("UPDATE discord.daily_prompt"):
                    channel_id, start, end = args
                    for row in self.rows.values():
                        if row["channel_id"] == channel_id and start <= row["created_at"] < end:
                            row["message_count"] += 1

        pool = DummyPool()
        cog.pool = pool

        await cog._archive_prompt("first", "cat", 5)
        await cog._archive_prompt("second", "cat", 5)

        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=5),
        )
        await cog.on_message(msg)

        counts = {row["prompt"]: row["message_count"] for row in pool.rows.values()}
        assert counts["first"] == 1
        assert counts["second"] == 1

    asyncio.run(run())


def test_on_message_ignores_previous_day():
    async def run():
        bot = types.SimpleNamespace()
        cog = prompt_cog.PromptCog(bot)

        class DummyPool:
            def __init__(self):
                self.rows = {}
                self.next_id = 1

            async def execute(self, query, *args):
                query = query.strip()
                if query.startswith("INSERT INTO discord.daily_prompt"):
                    prompt, category, channel_id, topic = args
                    now = prompt_cog.datetime.now(prompt_cog.ZoneInfo("UTC"))
                    self.rows[prompt] = {
                        "id": self.next_id,
                        "prompt": prompt,
                        "channel_id": channel_id,
                        "message_count": 0,
                        "created_at": now,
                        "topic": topic,
                    }
                    self.next_id += 1
                elif query.startswith("UPDATE discord.daily_prompt"):
                    channel_id, start, end = args
                    for row in self.rows.values():
                        if row["channel_id"] == channel_id and start <= row["created_at"] < end:
                            row["message_count"] += 1

        pool = DummyPool()
        cog.pool = pool

        await cog._archive_prompt("old", "cat", 5)
        pool.rows["old"]["created_at"] -= prompt_cog.timedelta(days=1)
        await cog._archive_prompt("new", "cat", 5)

        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=5),
        )
        await cog.on_message(msg)

        assert pool.rows["old"]["message_count"] == 0
        assert pool.rows["new"]["message_count"] == 1

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


def test_send_prompt_fetches_missing_channel(monkeypatch):
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

        async def fake_fetch_channel(_id):
            return channel

        bot = types.SimpleNamespace(get_channel=lambda _id: None, fetch_channel=fake_fetch_channel)
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

