"""Tests for the /mystats slash command cog."""
import asyncio
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from gentlebot.cogs import mystats_cog
from gentlebot.cogs.mystats_cog import (
    MyStatsCog,
    _format_hour,
    _format_percentile,
    TIMEFRAMES,
)
from gentlebot.queries import engagement as eq


# ── Helpers ────────────────────────────────────────────────────────────


def _make_cog(pool=None):
    """Create a MyStatsCog with a mock bot and optional pool."""
    bot = MagicMock()
    cog = MyStatsCog(bot)
    cog.pool = pool
    return cog


def _mock_member(uid=12345):
    """Return a mock Member."""
    member = MagicMock(spec=discord.Member)
    member.id = uid
    member.display_name = "TestUser"
    return member


_DEFAULT_QUERY_RESULTS = {
    "user_message_count": 127,
    "user_message_percentile": 0.85,
    "user_reactions_received": 43,
    "user_reaction_percentile": 0.78,
    "user_top_emojis_received": [("\u2764\ufe0f", 12), ("\U0001f602", 9), ("\U0001f525", 7)],
    "user_top_channels": [(10, "general", 52), (11, "gaming", 31), (12, "music", 18)],
    "user_peak_hour": 14,
    "user_hall_of_fame_count": 2,
    "user_fun_facts": {
        "first_seen_at": datetime(2024, 1, 15, tzinfo=timezone.utc),
        "lifetime_messages": 4231,
        "longest_message_len": 1847,
    },
}


def _build_embed(cog, member, uid, interval, timeframe, query_overrides=None):
    """Run _build_stats_embed with patched queries and return the embed."""
    values = {**_DEFAULT_QUERY_RESULTS, **(query_overrides or {})}
    with ExitStack() as stack:
        for name, val in values.items():
            stack.enter_context(
                patch.object(eq, name, new_callable=AsyncMock, return_value=val)
            )
        embed = asyncio.run(cog._build_stats_embed(member, uid, interval, timeframe))
    return embed


# ── Percentile formatting ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "pct, expected",
    [
        (0.95, "Top 5%"),
        (0.99, "Top 1%"),
        (0.90, "Top 10%"),
        (0.50, "Top 50%"),
        (0.49, None),    # Below 50% → omit
        (0.10, None),    # Bottom → omit
        (0.0, None),     # Lowest → omit
        (None, None),    # Missing → omit
        (1.0, "Top 1%"), # Edge: max rank clamps to 1%
    ],
)
def test_format_percentile(pct, expected):
    assert _format_percentile(pct) == expected


# ── Hour formatting ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "hour, expected",
    [
        (0, "12 AM PT"),
        (1, "1 AM PT"),
        (11, "11 AM PT"),
        (12, "12 PM PT"),
        (13, "1 PM PT"),
        (23, "11 PM PT"),
        (None, "N/A"),
    ],
)
def test_format_hour(hour, expected):
    assert _format_hour(hour) == expected


# ── Embed structure ────────────────────────────────────────────────────


def test_mystats_embed_structure():
    """Full embed should have all expected sections."""
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value={"current_streak": 12, "longest_streak": 28})
    cog = _make_cog(pool=pool)
    member = _mock_member()

    embed = _build_embed(cog, member, member.id, timedelta(days=30), "30d")

    field_names = [f.name for f in embed.fields]
    assert "Messages" in field_names
    assert "Reactions Received" in field_names
    assert "Streak" in field_names
    assert "Your Top Channels" in field_names
    assert "Your Vibe" in field_names
    assert "Fun Facts" in field_names

    # Footer
    assert embed.footer and "Only you can see this" in embed.footer.text

    # Color
    assert embed.color == discord.Color.blurple()


def test_mystats_no_activity():
    """Zero messages should produce a friendly fallback."""
    cog = _make_cog(pool=AsyncMock())
    member = _mock_member()

    embed = _build_embed(
        cog, member, member.id, timedelta(days=7), "7d",
        query_overrides={"user_message_count": 0},
    )

    assert "No activity" in embed.description
    assert embed.color == discord.Color.light_grey()
    # Should have no stat fields
    assert len(embed.fields) == 0


def test_mystats_ephemeral():
    """The mystats command should defer with ephemeral=True."""
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value={"current_streak": 5, "longest_streak": 10})
    cog = _make_cog(pool=pool)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = _mock_member()
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    values = {**_DEFAULT_QUERY_RESULTS}
    with ExitStack() as stack:
        for name, val in values.items():
            stack.enter_context(
                patch.object(eq, name, new_callable=AsyncMock, return_value=val)
            )
        # Use .callback to bypass the app_commands.Command wrapper
        asyncio.run(cog.mystats.callback(cog, interaction, timeframe="30d"))

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.followup.send.assert_awaited_once()
    call_kwargs = interaction.followup.send.call_args
    assert call_kwargs.kwargs.get("ephemeral") is True


def test_mystats_all_timeframes():
    """All 4 timeframe choices should produce a valid embed."""
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value={"current_streak": 1, "longest_streak": 5})
    cog = _make_cog(pool=pool)
    member = _mock_member()

    for tf_key, interval in TIMEFRAMES.items():
        embed = _build_embed(cog, member, member.id, interval, tf_key)
        assert isinstance(embed, discord.Embed)
        assert embed.title is not None


def test_mystats_percentile_display_top():
    """Top 15% user should see 'Top 15% of posters'."""
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value={"current_streak": 0, "longest_streak": 0})
    cog = _make_cog(pool=pool)
    member = _mock_member()

    embed = _build_embed(
        cog, member, member.id, timedelta(days=30), "30d",
        query_overrides={"user_message_percentile": 0.85},
    )

    msg_field = next(f for f in embed.fields if f.name == "Messages")
    assert "Top 15%" in msg_field.value


def test_mystats_percentile_display_bottom():
    """Below-50% user should not see percentile."""
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value={"current_streak": 0, "longest_streak": 0})
    cog = _make_cog(pool=pool)
    member = _mock_member()

    embed = _build_embed(
        cog, member, member.id, timedelta(days=30), "30d",
        query_overrides={"user_message_percentile": 0.30},
    )

    msg_field = next(f for f in embed.fields if f.name == "Messages")
    assert "Top" not in msg_field.value


def test_mystats_disabled():
    """Feature flag off should return a disabled message."""
    cog = _make_cog()

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = _mock_member()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch.object(mystats_cog.cfg, "MYSTATS_ENABLED", False):
        asyncio.run(cog.mystats.callback(cog, interaction, timeframe="30d"))

    interaction.response.send_message.assert_awaited_once()
    call_args = interaction.response.send_message.call_args
    assert "disabled" in call_args.args[0].lower()
    assert call_args.kwargs.get("ephemeral") is True


def test_mystats_streak_from_db():
    """Streak data should come from user_streak table."""
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value={"current_streak": 12, "longest_streak": 28})
    cog = _make_cog(pool=pool)
    member = _mock_member()

    embed = _build_embed(cog, member, member.id, timedelta(days=30), "30d")

    streak_field = next(f for f in embed.fields if f.name == "Streak")
    assert "12" in streak_field.value
    assert "28" in streak_field.value


def test_mystats_no_streak_record():
    """Missing streak row should show 0-day streak."""
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=None)
    cog = _make_cog(pool=pool)
    member = _mock_member()

    embed = _build_embed(cog, member, member.id, timedelta(days=30), "30d")

    streak_field = next(f for f in embed.fields if f.name == "Streak")
    assert "0" in streak_field.value


def test_mystats_hof_omitted_when_zero():
    """Hall of Fame line should be absent when count is zero."""
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value={"current_streak": 0, "longest_streak": 0})
    cog = _make_cog(pool=pool)
    member = _mock_member()

    embed = _build_embed(
        cog, member, member.id, timedelta(days=30), "30d",
        query_overrides={"user_hall_of_fame_count": 0},
    )

    vibe_field = next(f for f in embed.fields if f.name == "Your Vibe")
    assert "Hall of Fame" not in vibe_field.value
