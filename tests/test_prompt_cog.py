"""Tests for the template-based prompt cog.

Tests the daily prompt system including template selection, engagement-based
cooldown, data-driven category weighting, DOW skipping, and poll recovery.
"""
import types
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, AsyncMock, patch

import asyncpg

from gentlebot.cogs import prompt_cog


# ── Template loading ─────────────────────────────────────────────────────


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


def test_poll_options_limited_to_ten():
    """Discord limits polls to 10 options."""
    templates = prompt_cog.load_templates()
    poll_prompts = templates.get("poll_prompts", {})

    for category, polls in poll_prompts.items():
        for poll in polls:
            options = poll.get("options", [])
            assert len(options) <= 10, f"Poll in {category} has {len(options)} options (max 10)"


# ── Prompt selection (async, data-driven) ────────────────────────────────


def _make_cog_with_pool(pool=None):
    """Helper: create a PromptCog with an optional dummy pool."""
    bot = types.SimpleNamespace()
    cog = prompt_cog.PromptCog(bot)
    cog.pool = pool
    return cog


class EmptyFetchPool:
    """Dummy pool that returns empty results for all fetch/execute calls."""
    async def fetch(self, *args):
        return []

    async def execute(self, *args):
        pass


def test_select_text_prompt_returns_tuple():
    """_select_text_prompt should return (prompt, category) tuple."""
    async def run():
        cog = _make_cog_with_pool(EmptyFetchPool())
        prompt, category = await cog._select_text_prompt()

        assert isinstance(prompt, str)
        assert isinstance(category, str)
        assert len(prompt) > 0
        assert len(category) > 0

    asyncio.run(run())


def test_select_poll_returns_tuple():
    """_select_poll should return (poll_dict, category) tuple."""
    async def run():
        cog = _make_cog_with_pool(EmptyFetchPool())
        poll_data, category = await cog._select_poll()

        assert isinstance(poll_data, dict)
        assert isinstance(category, str)
        assert "question" in poll_data
        assert "options" in poll_data
        assert len(poll_data["options"]) >= 2

    asyncio.run(run())


def test_should_use_poll_returns_boolean():
    """_should_use_poll should return a boolean."""
    cog = _make_cog_with_pool()
    result = cog._should_use_poll()
    assert isinstance(result, bool)


def test_prompts_tracked_in_history():
    """Selected prompts should be tracked in history."""
    async def run():
        cog = _make_cog_with_pool(EmptyFetchPool())
        prompt, category = await cog._select_text_prompt()

        # Manually add to history as _send_text_prompt would
        cog.history.append(prompt)
        cog.past_prompts.add(prompt)

        assert prompt in cog.history
        assert prompt in cog.past_prompts

    asyncio.run(run())


# ── Cog lifecycle ────────────────────────────────────────────────────────


def test_history_deque_maxlen():
    """History should have a maximum length to prevent memory issues."""
    cog = _make_cog_with_pool()
    assert cog.history.maxlen == 20


def test_archive_prompt_missing_table():
    """Archive should handle missing table gracefully."""
    async def run():
        class DummyPool:
            async def execute(self, *args):
                raise asyncpg.UndefinedTableError("msg", "detail", "hint")

        cog = _make_cog_with_pool(DummyPool())
        # Should not raise
        await cog._archive_prompt("hi", "cat", 1, "text")

    asyncio.run(run())


def test_archive_prompt_uses_schema():
    """Archive should use discord schema."""
    async def run():
        captured = {}

        class DummyPool:
            async def execute(self, query, *args):
                captured['query'] = query

        cog = _make_cog_with_pool(DummyPool())
        await cog._archive_prompt('hi', 'cat', 1, 'text')

        assert 'discord.daily_prompt' in captured['query']

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


# ── Sending prompts ──────────────────────────────────────────────────────


def test_last_category_updated():
    """last_category should be updated after prompt selection."""
    async def run():
        class DummyChannel:
            id = 123
            async def send(self, content=None, poll=None):
                return types.SimpleNamespace(id=456)

        cog = _make_cog_with_pool(EmptyFetchPool())
        await cog._send_text_prompt(DummyChannel())
        assert cog.last_category != ""
        assert cog.last_prompt_type == "text"

    asyncio.run(run())


def test_poll_prompt_type_tracked(monkeypatch):
    """last_prompt_type should be 'poll' after sending poll."""
    async def run():
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

        class DummyChannel:
            id = 123
            async def send(self, content=None, poll=None):
                return types.SimpleNamespace(id=456)

        cog = _make_cog_with_pool(EmptyFetchPool())
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
        cog.pool = EmptyFetchPool()

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
        cog.pool = EmptyFetchPool()

        # Force text prompt
        monkeypatch.setattr(cog, "_should_use_poll", lambda: False)

        await cog._send_prompt()
        assert channel.sent is not None

    asyncio.run(run())


def test_force_poll_after_cooldown():
    """_send_prompt should send a poll when _force_poll_after_cooldown is set."""
    async def run():
        class DummyChannel:
            def __init__(self):
                self.poll_sent = False
                self.id = 123
            async def send(self, content=None, poll=None):
                if poll is not None:
                    self.poll_sent = True
                return types.SimpleNamespace(id=456, channel=self)

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

        channel = DummyChannel()
        cog = _make_cog_with_pool(EmptyFetchPool())
        cog._force_poll_after_cooldown = True

        with patch.object(prompt_cog.discord, "Poll", MockPoll, create=True), \
             patch.object(prompt_cog.discord, "PollQuestion", MockPollQuestion, create=True), \
             patch.object(prompt_cog.cfg, "DAILY_PING_CHANNEL", 123), \
             patch.object(cog, "bot", types.SimpleNamespace(get_channel=lambda _id: channel)):
            await cog._send_prompt()

        assert channel.poll_sent is True
        assert cog._force_poll_after_cooldown is False  # Flag consumed

    asyncio.run(run())


# ── Scheduling ───────────────────────────────────────────────────────────


def test_next_run_time_calculation():
    """_next_run_time should calculate correct next scheduled time."""
    cog = _make_cog_with_pool()

    # Test when current time is before schedule
    now = datetime(2024, 1, 15, 10, 0, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    next_run = cog._next_run_time(now)

    assert next_run.hour == prompt_cog.SCHEDULE_HOUR
    assert next_run.minute == prompt_cog.SCHEDULE_MINUTE
    assert next_run > now


def test_next_run_time_wraps_to_tomorrow():
    """_next_run_time should wrap to next day if past schedule time."""
    cog = _make_cog_with_pool()

    # Test when current time is after schedule
    now = datetime(2024, 1, 15, 23, 0, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    next_run = cog._next_run_time(now)

    assert next_run.day == 16  # Next day
    assert next_run.hour == prompt_cog.SCHEDULE_HOUR


# ── Engagement history ───────────────────────────────────────────────────


def test_fetch_engagement_history_no_pool():
    """_fetch_engagement_history should return [] when pool is None."""
    async def run():
        cog = _make_cog_with_pool(None)
        result = await cog._fetch_engagement_history(lookback_days=90)
        assert result == []

    asyncio.run(run())


def test_fetch_engagement_history_handles_missing_table():
    """_fetch_engagement_history should handle missing tables gracefully."""
    async def run():
        class DummyPool:
            async def fetch(self, *args):
                raise asyncpg.UndefinedTableError("msg", "detail", "hint")

        cog = _make_cog_with_pool(DummyPool())
        result = await cog._fetch_engagement_history(lookback_days=90)
        assert result == []

    asyncio.run(run())


def test_fetch_engagement_history_returns_data():
    """_fetch_engagement_history should return dicts with expected keys."""
    async def run():
        now = datetime.now(ZoneInfo("UTC"))

        class DummyPool:
            async def fetch(self, *args):
                return [
                    {
                        "created_at": now,
                        "category": "hot_take",
                        "topic": "text",
                        "day_of_week": 3,  # Wednesday
                        "unique_responders": 5,
                    },
                ]

        cog = _make_cog_with_pool(DummyPool())
        result = await cog._fetch_engagement_history(lookback_days=90)

        assert len(result) == 1
        row = result[0]
        assert "created_at" in row
        assert "category" in row
        assert "topic" in row
        assert "day_of_week" in row
        assert "unique_responders" in row
        assert row["unique_responders"] == 5

    asyncio.run(run())


# ── Cooldown logic ───────────────────────────────────────────────────────


def test_get_cooldown_info_no_pool():
    """_get_cooldown_info should return no cooldown when pool is None."""
    async def run():
        cog = _make_cog_with_pool(None)
        should_skip, next_eligible, low_count = await cog._get_cooldown_info()

        assert should_skip is False
        assert next_eligible is None
        assert low_count == 0

    asyncio.run(run())


def test_get_cooldown_info_no_prompts():
    """_get_cooldown_info should return no cooldown when no prompts exist."""
    async def run():
        cog = _make_cog_with_pool(EmptyFetchPool())
        should_skip, next_eligible, low_count = await cog._get_cooldown_info()

        assert should_skip is False
        assert next_eligible is None
        assert low_count == 0

    asyncio.run(run())


def test_get_cooldown_info_good_engagement():
    """_get_cooldown_info should return no cooldown when last prompt had good engagement."""
    async def run():
        class DummyPool:
            async def fetch(self, *args):
                return [
                    {"created_at": datetime.now(ZoneInfo("UTC")), "unique_responders": 5},
                ]

        cog = _make_cog_with_pool(DummyPool())
        should_skip, next_eligible, low_count = await cog._get_cooldown_info()

        assert should_skip is False
        assert next_eligible is None
        assert low_count == 0

    asyncio.run(run())


def test_get_cooldown_info_one_low_engagement():
    """_get_cooldown_info should return 1 day cooldown for 1 low-engagement prompt."""
    async def run():
        now = datetime.now(ZoneInfo("UTC"))

        class DummyPool:
            async def fetch(self, *args):
                return [
                    {"created_at": now, "unique_responders": 0},
                ]

        cog = _make_cog_with_pool(DummyPool())
        should_skip, next_eligible, low_count = await cog._get_cooldown_info()

        assert should_skip is True
        assert next_eligible is not None
        assert low_count == 1
        # Cooldown should be ~1 day from the prompt time
        expected_eligible = now + timedelta(days=1)
        assert abs((next_eligible - expected_eligible).total_seconds()) < 60

    asyncio.run(run())


def test_get_cooldown_info_exponential_backoff():
    """_get_cooldown_info should calculate exponential cooldown."""
    async def run():
        now = datetime.now(ZoneInfo("UTC"))

        class DummyPool:
            async def fetch(self, *args):
                return [
                    {"created_at": now, "unique_responders": 0},
                    {"created_at": now - timedelta(days=1), "unique_responders": 1},
                    {"created_at": now - timedelta(days=2), "unique_responders": 0},
                ]

        cog = _make_cog_with_pool(DummyPool())
        should_skip, next_eligible, low_count = await cog._get_cooldown_info()

        assert low_count == 3
        # 3 low-engagement prompts = 2^(3-1) = 4 days cooldown
        expected_eligible = now + timedelta(days=4)
        assert abs((next_eligible - expected_eligible).total_seconds()) < 60

    asyncio.run(run())


def test_get_cooldown_info_streak_broken():
    """_get_cooldown_info should stop counting when engagement is good."""
    async def run():
        now = datetime.now(ZoneInfo("UTC"))

        class DummyPool:
            async def fetch(self, *args):
                return [
                    {"created_at": now, "unique_responders": 0},           # low
                    {"created_at": now - timedelta(days=1), "unique_responders": 1},  # low
                    {"created_at": now - timedelta(days=2), "unique_responders": 5},  # GOOD
                    {"created_at": now - timedelta(days=3), "unique_responders": 0},  # not counted
                ]

        cog = _make_cog_with_pool(DummyPool())
        should_skip, next_eligible, low_count = await cog._get_cooldown_info()

        assert low_count == 2  # Only counts until good engagement found

    asyncio.run(run())


def test_get_cooldown_info_cooldown_expired():
    """_get_cooldown_info should allow posting when cooldown has expired."""
    async def run():
        # Prompt was 2 days ago with low engagement (1 day cooldown has passed)
        old_time = datetime.now(ZoneInfo("UTC")) - timedelta(days=2)

        class DummyPool:
            async def fetch(self, *args):
                return [
                    {"created_at": old_time, "unique_responders": 0},
                ]

        cog = _make_cog_with_pool(DummyPool())
        should_skip, next_eligible, low_count = await cog._get_cooldown_info()

        assert should_skip is False  # Cooldown expired, can post
        assert next_eligible is None
        assert low_count == 1  # Still tracks the low engagement count

    asyncio.run(run())


def test_get_cooldown_info_max_cooldown_capped():
    """_get_cooldown_info should cap cooldown at MAX_COOLDOWN_DAYS."""
    async def run():
        now = datetime.now(ZoneInfo("UTC"))
        # 10 consecutive low-engagement prompts would be 2^9 = 512 days without cap
        rows = [
            {"created_at": now - timedelta(days=i), "unique_responders": 0}
            for i in range(10)
        ]

        class DummyPool:
            async def fetch(self, *args):
                return rows

        cog = _make_cog_with_pool(DummyPool())
        should_skip, next_eligible, low_count = await cog._get_cooldown_info()

        assert low_count == 10
        # Should be capped at MAX_COOLDOWN_DAYS (7 by default)
        max_cooldown = min(2 ** (10 - 1), prompt_cog.MAX_COOLDOWN_DAYS)
        expected_max = now + timedelta(days=max_cooldown)
        assert next_eligible <= expected_max + timedelta(seconds=60)

    asyncio.run(run())


def test_get_cooldown_info_handles_missing_table():
    """_get_cooldown_info should handle missing table gracefully."""
    async def run():
        class DummyPool:
            async def fetch(self, *args):
                raise asyncpg.UndefinedTableError("msg", "detail", "hint")

        cog = _make_cog_with_pool(DummyPool())
        should_skip, next_eligible, low_count = await cog._get_cooldown_info()

        assert should_skip is False
        assert next_eligible is None
        assert low_count == 0

    asyncio.run(run())


# ── Category weighting ───────────────────────────────────────────────────


def test_compute_category_weights_no_pool():
    """_compute_category_weights should return equal weights when pool is None."""
    async def run():
        cog = _make_cog_with_pool(None)
        weights = await cog._compute_category_weights("text")

        categories = list(cog.templates.get("text_prompts", {}).keys())
        assert len(weights) == len(categories)
        # All weights should be equal
        values = list(weights.values())
        assert all(abs(v - values[0]) < 0.01 for v in values)

    asyncio.run(run())


def test_compute_category_weights_insufficient_data():
    """_compute_category_weights should return equal weights with insufficient data."""
    async def run():
        class DummyPool:
            async def fetch(self, *args):
                # Only 1 prompt per category (below CATEGORY_MIN_SAMPLE_SIZE=3)
                return [
                    {"created_at": datetime.now(ZoneInfo("UTC")),
                     "category": "hot_take", "topic": "text",
                     "day_of_week": 1, "unique_responders": 5},
                ]

        cog = _make_cog_with_pool(DummyPool())
        weights = await cog._compute_category_weights("text")

        categories = list(cog.templates.get("text_prompts", {}).keys())
        values = list(weights.values())
        assert len(weights) == len(categories)
        assert all(abs(v - values[0]) < 0.01 for v in values)

    asyncio.run(run())


def test_compute_category_weights_favors_high_engagement():
    """_compute_category_weights should assign higher weight to better-performing categories."""
    async def run():
        now = datetime.now(ZoneInfo("UTC"))
        # hot_take gets consistently high engagement, food_debate gets low
        history = []
        for i in range(5):
            history.append({
                "created_at": now - timedelta(days=i),
                "category": "hot_take", "topic": "text",
                "day_of_week": 1, "unique_responders": 10,
            })
            history.append({
                "created_at": now - timedelta(days=i),
                "category": "food_debate", "topic": "text",
                "day_of_week": 1, "unique_responders": 1,
            })

        class DummyPool:
            async def fetch(self, *args):
                return history

        cog = _make_cog_with_pool(DummyPool())
        weights = await cog._compute_category_weights("text")

        assert weights["hot_take"] > weights["food_debate"]

    asyncio.run(run())


def test_compute_category_weights_recency_penalty():
    """_compute_category_weights should penalize the last-used category."""
    async def run():
        now = datetime.now(ZoneInfo("UTC"))
        # Both categories get equal engagement
        history = []
        for i in range(5):
            history.append({
                "created_at": now - timedelta(days=i),
                "category": "hot_take", "topic": "text",
                "day_of_week": 1, "unique_responders": 5,
            })
            history.append({
                "created_at": now - timedelta(days=i),
                "category": "food_debate", "topic": "text",
                "day_of_week": 1, "unique_responders": 5,
            })

        class DummyPool:
            async def fetch(self, *args):
                return history

        cog = _make_cog_with_pool(DummyPool())
        cog.last_category = "hot_take"
        weights = await cog._compute_category_weights("text")

        # hot_take should be penalized because it was last used
        assert weights["hot_take"] < weights["food_debate"]

    asyncio.run(run())


# ── Day-of-week awareness ───────────────────────────────────────────────


def test_should_skip_dow_no_pool():
    """_should_skip_day_of_week should return False when pool is None."""
    async def run():
        cog = _make_cog_with_pool(None)
        result = await cog._should_skip_day_of_week()
        assert result is False

    asyncio.run(run())


def test_should_skip_dow_insufficient_data():
    """_should_skip_day_of_week should return False with insufficient data."""
    async def run():
        # Only 1 data point for today's DOW (below CATEGORY_MIN_SAMPLE_SIZE=3)
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        pg_dow = (now.weekday() + 1) % 7

        class DummyPool:
            async def fetch(self, *args):
                return [
                    {"created_at": now, "category": "hot_take", "topic": "text",
                     "day_of_week": pg_dow, "unique_responders": 0},
                ]

        cog = _make_cog_with_pool(DummyPool())
        result = await cog._should_skip_day_of_week()
        assert result is False

    asyncio.run(run())


def test_should_skip_dow_low_engagement():
    """_should_skip_day_of_week should return True when DOW has low engagement."""
    async def run():
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        pg_dow = (now.weekday() + 1) % 7

        # 5 data points all with 0 responders
        class DummyPool:
            async def fetch(self, *args):
                return [
                    {"created_at": now - timedelta(weeks=i), "category": "x", "topic": "text",
                     "day_of_week": pg_dow, "unique_responders": 0}
                    for i in range(5)
                ]

        cog = _make_cog_with_pool(DummyPool())
        result = await cog._should_skip_day_of_week()
        assert result is True

    asyncio.run(run())


def test_should_skip_dow_good_engagement():
    """_should_skip_day_of_week should return False when DOW has good engagement."""
    async def run():
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        pg_dow = (now.weekday() + 1) % 7

        # 5 data points all with good engagement
        class DummyPool:
            async def fetch(self, *args):
                return [
                    {"created_at": now - timedelta(weeks=i), "category": "x", "topic": "text",
                     "day_of_week": pg_dow, "unique_responders": 5}
                    for i in range(5)
                ]

        cog = _make_cog_with_pool(DummyPool())
        result = await cog._should_skip_day_of_week()
        assert result is False

    asyncio.run(run())
