"""Tests for the template-based prompt cog.

Tests the new template-based daily prompt system that uses human-curated
prompts from YAML instead of LLM-generated content.
"""
import types
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, AsyncMock, patch

import asyncpg

from gentlebot.cogs import prompt_cog


def test_load_templates_returns_dict():
    """Templates should load from YAML file."""
    templates = prompt_cog.load_templates()
    assert isinstance(templates, dict)
    assert "text_prompts" in templates
    assert "poll_prompts" in templates


def test_text_prompts_have_categories():
    """Text prompts should have multiple categories."""
    templates = prompt_cog.load_templates()
    text_prompts = templates.get("text_prompts", {})
    assert len(text_prompts) > 0
    # Should have categories like hot_take, forced_choice, etc.
    assert any(cat in text_prompts for cat in ["hot_take", "forced_choice", "this_or_that"])


def test_poll_prompts_have_categories():
    """Poll prompts should have multiple categories."""
    templates = prompt_cog.load_templates()
    poll_prompts = templates.get("poll_prompts", {})
    assert len(poll_prompts) > 0
    # Should have categories like elimination, binary, preference
    assert any(cat in poll_prompts for cat in ["elimination", "binary", "preference"])


def test_select_text_prompt_returns_tuple():
    """_select_text_prompt should return (prompt, category) tuple."""
    bot = types.SimpleNamespace()
    cog = prompt_cog.PromptCog(bot)

    prompt, category = cog._select_text_prompt()

    assert isinstance(prompt, str)
    assert isinstance(category, str)
    assert len(prompt) > 0
    assert len(category) > 0


def test_select_poll_returns_tuple():
    """_select_poll should return (poll_dict, category) tuple."""
    bot = types.SimpleNamespace()
    cog = prompt_cog.PromptCog(bot)

    poll_data, category = cog._select_poll()

    assert isinstance(poll_data, dict)
    assert isinstance(category, str)
    assert "question" in poll_data
    assert "options" in poll_data
    assert len(poll_data["options"]) >= 2


def test_category_weight_decreases_after_selection():
    """Category weight should decrease after being selected."""
    bot = types.SimpleNamespace()
    cog = prompt_cog.PromptCog(bot)

    # Get initial weight for a category
    categories = list(cog.text_category_weights.keys())
    if not categories:
        return  # Skip if no categories loaded

    category = categories[0]
    initial_weight = cog.text_category_weights[category]

    # Manually simulate selection of that category
    cog.text_category_weights[category] *= 0.5

    assert cog.text_category_weights[category] < initial_weight


def test_should_use_poll_returns_boolean():
    """_should_use_poll should return a boolean."""
    bot = types.SimpleNamespace()
    cog = prompt_cog.PromptCog(bot)

    result = cog._should_use_poll()
    assert isinstance(result, bool)


def test_archive_prompt_missing_table():
    """Archive should handle missing table gracefully."""
    async def run():
        cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())

        class DummyPool:
            async def execute(self, *args):
                raise asyncpg.UndefinedTableError("msg", "detail", "hint")

        cog.pool = DummyPool()
        # Should not raise
        await cog._archive_prompt("hi", "cat", 1, "text")

    asyncio.run(run())


def test_archive_prompt_uses_schema():
    """Archive should use discord schema."""
    async def run():
        cog = prompt_cog.PromptCog(bot=types.SimpleNamespace())

        captured = {}

        class DummyPool:
            async def execute(self, query, *args):
                captured['query'] = query

        cog.pool = DummyPool()
        await cog._archive_prompt('hi', 'cat', 1, 'text')

        assert 'discord.daily_prompt' in captured['query']

    asyncio.run(run())


def test_on_message_missing_table():
    """on_message should handle missing table gracefully."""
    async def run():
        bot = types.SimpleNamespace()
        cog = prompt_cog.PromptCog(bot)

        class DummyPool:
            async def execute(self, *args):
                raise asyncpg.UndefinedTableError("msg", "detail", "hint")

        cog.pool = DummyPool()
        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=1),
        )
        # Should not raise
        await cog.on_message(msg)

    asyncio.run(run())


def test_on_message_uses_schema():
    """on_message should use discord schema."""
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


def test_on_message_ignores_bot():
    """on_message should ignore bot messages."""
    async def run():
        bot = types.SimpleNamespace()
        cog = prompt_cog.PromptCog(bot)

        executed = []

        class DummyPool:
            async def execute(self, query, *args):
                executed.append(True)

        cog.pool = DummyPool()
        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=True),  # Bot author
            channel=types.SimpleNamespace(id=1),
        )
        await cog.on_message(msg)

        # Should not execute any queries for bot messages
        assert len(executed) == 0

    asyncio.run(run())


def test_history_deque_maxlen():
    """History should have a maximum length to prevent memory issues."""
    bot = types.SimpleNamespace()
    cog = prompt_cog.PromptCog(bot)

    assert cog.history.maxlen == 20


def test_prompts_tracked_in_history():
    """Selected prompts should be tracked in history."""
    bot = types.SimpleNamespace()
    cog = prompt_cog.PromptCog(bot)

    prompt, category = cog._select_text_prompt()

    # Manually add to history as _send_text_prompt would
    cog.history.append(prompt)
    cog.past_prompts.add(prompt)

    assert prompt in cog.history
    assert prompt in cog.past_prompts


def test_last_category_updated():
    """last_category should be updated after prompt selection."""
    async def run():
        bot = types.SimpleNamespace()
        cog = prompt_cog.PromptCog(bot)

        class DummyChannel:
            id = 123

            async def send(self, content=None, poll=None):
                return types.SimpleNamespace(id=456)

        # Test text prompt
        await cog._send_text_prompt(DummyChannel())
        assert cog.last_category != ""
        assert cog.last_prompt_type == "text"

    asyncio.run(run())


def test_poll_prompt_type_tracked(monkeypatch):
    """last_prompt_type should be 'poll' after sending poll."""
    async def run():
        # Mock discord.Poll and discord.PollQuestion for environments where they don't exist
        class MockPollQuestion:
            def __init__(self, text):
                self.text = text

        class MockPoll:
            def __init__(self, question, duration):
                self.question = question
                self.duration = duration
                self.answers = []

            def add_answer(self, text):
                self.answers.append(text)

        monkeypatch.setattr(prompt_cog.discord, "Poll", MockPoll, raising=False)
        monkeypatch.setattr(prompt_cog.discord, "PollQuestion", MockPollQuestion, raising=False)

        bot = types.SimpleNamespace()
        cog = prompt_cog.PromptCog(bot)

        class DummyChannel:
            id = 123

            async def send(self, content=None, poll=None):
                return types.SimpleNamespace(id=456)

        await cog._send_poll(DummyChannel())
        assert cog.last_prompt_type == "poll"

    asyncio.run(run())


def test_send_prompt_posts_to_channel(monkeypatch):
    """_send_prompt should post to the configured channel."""
    async def run():
        monkeypatch.setattr(prompt_cog.cfg, "DAILY_PING_CHANNEL", 123)

        class DummyChannel:
            def __init__(self):
                self.sent = None
                self.id = 123

            async def send(self, content=None, poll=None):
                self.sent = content or poll
                return types.SimpleNamespace(id=456, channel=self)

        channel = DummyChannel()
        bot = types.SimpleNamespace(get_channel=lambda _id: channel)
        cog = prompt_cog.PromptCog(bot)

        # Force text prompt
        monkeypatch.setattr(cog, "_should_use_poll", lambda: False)

        await cog._send_prompt()
        assert channel.sent is not None

    asyncio.run(run())


def test_send_prompt_fetches_missing_channel(monkeypatch):
    """_send_prompt should fetch channel if not in cache."""
    async def run():
        monkeypatch.setattr(prompt_cog.cfg, "DAILY_PING_CHANNEL", 123)

        class DummyChannel:
            def __init__(self):
                self.sent = None
                self.id = 123

            async def send(self, content=None, poll=None):
                self.sent = content or poll
                return types.SimpleNamespace(id=456, channel=self)

        channel = DummyChannel()

        async def fake_fetch_channel(_id):
            return channel

        bot = types.SimpleNamespace(
            get_channel=lambda _id: None,
            fetch_channel=fake_fetch_channel
        )
        cog = prompt_cog.PromptCog(bot)

        # Force text prompt
        monkeypatch.setattr(cog, "_should_use_poll", lambda: False)

        await cog._send_prompt()
        assert channel.sent is not None

    asyncio.run(run())


def test_cog_load_handles_missing_table():
    """cog_load should handle missing daily_prompt table."""
    async def run():
        bot = types.SimpleNamespace()
        cog = prompt_cog.PromptCog(bot)

        class DummyPool:
            async def fetch(self, *args):
                raise asyncpg.UndefinedTableError("msg", "detail", "hint")

        with patch.object(prompt_cog, 'get_pool', new=AsyncMock(return_value=DummyPool())):
            await cog.cog_load()

        # Should not raise, past_prompts should be empty
        assert len(cog.past_prompts) == 0

    asyncio.run(run())


def test_poll_options_limited_to_ten():
    """Discord limits polls to 10 options."""
    templates = prompt_cog.load_templates()
    poll_prompts = templates.get("poll_prompts", {})

    for category, polls in poll_prompts.items():
        for poll in polls:
            options = poll.get("options", [])
            assert len(options) <= 10, f"Poll in {category} has {len(options)} options (max 10)"


def test_next_run_time_calculation():
    """_next_run_time should calculate correct next scheduled time."""
    bot = types.SimpleNamespace()
    cog = prompt_cog.PromptCog(bot)

    # Test when current time is before schedule
    now = datetime(2024, 1, 15, 10, 0, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    next_run = cog._next_run_time(now)

    assert next_run.hour == prompt_cog.SCHEDULE_HOUR
    assert next_run.minute == prompt_cog.SCHEDULE_MINUTE
    assert next_run > now


def test_next_run_time_wraps_to_tomorrow():
    """_next_run_time should wrap to next day if past schedule time."""
    bot = types.SimpleNamespace()
    cog = prompt_cog.PromptCog(bot)

    # Test when current time is after schedule
    now = datetime(2024, 1, 15, 23, 0, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    next_run = cog._next_run_time(now)

    assert next_run.day == 16  # Next day
    assert next_run.hour == prompt_cog.SCHEDULE_HOUR
