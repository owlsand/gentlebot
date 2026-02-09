"""Tests for the shared engagement query module."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from gentlebot.queries import engagement as eq


# ── Helper: mock pool ──────────────────────────────────────────────────


def _mock_pool(fetchval=None, fetch=None, fetchrow=None):
    """Return an AsyncMock pool with configurable return values."""
    pool = AsyncMock()
    pool.fetchval = AsyncMock(return_value=fetchval)
    pool.fetch = AsyncMock(return_value=fetch or [])
    pool.fetchrow = AsyncMock(return_value=fetchrow)
    return pool


# ── Pool-is-None defaults ─────────────────────────────────────────────


def test_server_message_count_none_pool():
    result = asyncio.run(eq.server_message_count(None, "7 days"))
    assert result == 0


def test_unique_posters_none_pool():
    assert asyncio.run(eq.unique_posters(None, "7 days")) == 0


def test_top_posters_none_pool():
    assert asyncio.run(eq.top_posters(None, "7 days")) == []


def test_top_reaction_receivers_none_pool():
    assert asyncio.run(eq.top_reaction_receivers(None, "7 days")) == []


def test_most_active_channels_none_pool():
    assert asyncio.run(eq.most_active_channels(None, "7 days")) == []


def test_top_reacted_message_none_pool():
    assert asyncio.run(eq.top_reacted_message(None, "7 days")) is None


def test_new_member_count_none_pool():
    assert asyncio.run(eq.new_member_count(None, "7 days")) == 0


def test_active_streak_counts_none_pool():
    assert asyncio.run(eq.active_streak_counts(None)) == (0, 0)


def test_new_hof_count_none_pool():
    assert asyncio.run(eq.new_hof_count(None, "7 days")) == 0


def test_user_message_count_none_pool():
    assert asyncio.run(eq.user_message_count(None, 123, "7 days")) == 0


def test_user_message_percentile_none_pool():
    assert asyncio.run(eq.user_message_percentile(None, 123, "7 days")) is None


def test_user_reactions_received_none_pool():
    assert asyncio.run(eq.user_reactions_received(None, 123, "7 days")) == 0


def test_user_top_emojis_received_none_pool():
    assert asyncio.run(eq.user_top_emojis_received(None, 123, "7 days")) == []


def test_user_top_channels_none_pool():
    assert asyncio.run(eq.user_top_channels(None, 123, "7 days")) == []


def test_user_peak_hour_none_pool():
    assert asyncio.run(eq.user_peak_hour(None, 123, "7 days")) is None


def test_user_hall_of_fame_count_none_pool():
    assert asyncio.run(eq.user_hall_of_fame_count(None, 123)) == 0


def test_user_fun_facts_none_pool():
    result = asyncio.run(eq.user_fun_facts(None, 123))
    assert result["first_seen_at"] is None
    assert result["lifetime_messages"] == 0
    assert result["longest_message_len"] == 0


def test_user_reaction_percentile_none_pool():
    assert asyncio.run(eq.user_reaction_percentile(None, 123, "7 days")) is None


# ── With mock pool ─────────────────────────────────────────────────────


def test_server_message_count_returns_int():
    pool = _mock_pool(fetchval=42)
    result = asyncio.run(eq.server_message_count(pool, "7 days"))
    assert result == 42
    pool.fetchval.assert_awaited_once()


def test_unique_posters_returns_int():
    pool = _mock_pool(fetchval=10)
    assert asyncio.run(eq.unique_posters(pool, "7 days")) == 10


def test_top_posters_returns_list():
    rows = [{"author_id": 1, "cnt": 50}, {"author_id": 2, "cnt": 30}]
    pool = _mock_pool(fetch=rows)
    result = asyncio.run(eq.top_posters(pool, "7 days"))
    assert result == [(1, 50), (2, 30)]


def test_top_reaction_receivers_returns_list():
    rows = [{"author_id": 5, "cnt": 20}]
    pool = _mock_pool(fetch=rows)
    result = asyncio.run(eq.top_reaction_receivers(pool, "7 days"))
    assert result == [(5, 20)]


def test_most_active_channels_returns_list():
    rows = [{"channel_id": 100, "name": "general", "cnt": 200}]
    pool = _mock_pool(fetch=rows)
    result = asyncio.run(eq.most_active_channels(pool, "7 days"))
    assert result == [(100, "general", 200)]


def test_top_reacted_message_returns_dict():
    row = {
        "message_id": 99,
        "channel_id": 10,
        "channel_name": "general",
        "author_id": 1,
        "content": "Hello!",
        "reaction_count": 15,
    }
    pool = _mock_pool(fetchrow=row)
    result = asyncio.run(eq.top_reacted_message(pool, "7 days"))
    assert result["message_id"] == 99
    assert result["reaction_count"] == 15


def test_top_reacted_message_returns_none():
    pool = _mock_pool(fetchrow=None)
    result = asyncio.run(eq.top_reacted_message(pool, "7 days"))
    assert result is None


def test_new_member_count_returns_int():
    pool = _mock_pool(fetchval=3)
    assert asyncio.run(eq.new_member_count(pool, "7 days")) == 3


def test_active_streak_counts_returns_tuple():
    pool = _mock_pool(fetchrow={"total_active": 14, "strong": 5})
    result = asyncio.run(eq.active_streak_counts(pool))
    assert result == (14, 5)


def test_active_streak_counts_none_row():
    pool = _mock_pool(fetchrow=None)
    result = asyncio.run(eq.active_streak_counts(pool))
    assert result == (0, 0)


def test_new_hof_count_returns_int():
    pool = _mock_pool(fetchval=2)
    assert asyncio.run(eq.new_hof_count(pool, "7 days")) == 2


def test_user_message_count_returns_int():
    pool = _mock_pool(fetchval=127)
    assert asyncio.run(eq.user_message_count(pool, 1, "30 days")) == 127


def test_user_message_percentile_returns_float():
    pool = _mock_pool(fetchval=0.85)
    result = asyncio.run(eq.user_message_percentile(pool, 1, "30 days"))
    assert result == 0.85


def test_user_reactions_received_returns_int():
    pool = _mock_pool(fetchval=43)
    assert asyncio.run(eq.user_reactions_received(pool, 1, "30 days")) == 43


def test_user_top_emojis_returns_list():
    rows = [{"emoji": "\u2764\ufe0f", "cnt": 12}, {"emoji": "\U0001f602", "cnt": 9}]
    pool = _mock_pool(fetch=rows)
    result = asyncio.run(eq.user_top_emojis_received(pool, 1, "30 days"))
    assert result == [("\u2764\ufe0f", 12), ("\U0001f602", 9)]


def test_user_top_channels_returns_list():
    rows = [{"channel_id": 10, "name": "general", "cnt": 52}]
    pool = _mock_pool(fetch=rows)
    result = asyncio.run(eq.user_top_channels(pool, 1, "30 days"))
    assert result == [(10, "general", 52)]


def test_user_peak_hour_returns_int():
    pool = _mock_pool(fetchval=14)
    assert asyncio.run(eq.user_peak_hour(pool, 1, "30 days")) == 14


def test_user_hall_of_fame_count_returns_int():
    pool = _mock_pool(fetchval=2)
    assert asyncio.run(eq.user_hall_of_fame_count(pool, 1)) == 2


def test_user_fun_facts_returns_dict():
    from datetime import datetime, timezone

    row = {
        "first_seen_at": datetime(2024, 1, 15, tzinfo=timezone.utc),
        "lifetime_messages": 4231,
        "longest_message_len": 1847,
    }
    pool = _mock_pool(fetchrow=row)
    result = asyncio.run(eq.user_fun_facts(pool, 1))
    assert result["lifetime_messages"] == 4231
    assert result["longest_message_len"] == 1847


def test_user_fun_facts_none_row():
    pool = _mock_pool(fetchrow=None)
    result = asyncio.run(eq.user_fun_facts(pool, 1))
    assert result["first_seen_at"] is None
    assert result["lifetime_messages"] == 0


def test_user_reaction_percentile_returns_float():
    pool = _mock_pool(fetchval=0.78)
    result = asyncio.run(eq.user_reaction_percentile(pool, 1, "30 days"))
    assert result == 0.78


def test_server_message_count_null_fetchval():
    """fetchval returning None should be coerced to 0."""
    pool = _mock_pool(fetchval=None)
    assert asyncio.run(eq.server_message_count(pool, "7 days")) == 0
