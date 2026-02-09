"""Tests for the weekly recap cog."""
import asyncio
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from gentlebot.cogs import weekly_recap_cog
from gentlebot.cogs.weekly_recap_cog import WeeklyRecapCog, _delta_str, _week_range_title
from gentlebot.queries import engagement as eq


# ── Helpers ────────────────────────────────────────────────────────────


def _make_cog(pool=None):
    """Create a WeeklyRecapCog with a mock bot and optional pool."""
    bot = MagicMock()
    bot.wait_until_ready = AsyncMock()
    cog = WeeklyRecapCog(bot)
    cog.pool = pool
    return cog


def _mock_guild():
    """Return a mock Guild with basic attributes."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 123456789
    guild.name = "Gentlefolk"
    return guild


# Default canned query results for patching
_DEFAULT_PATCHES = {
    "server_message_count": 1247,
    "unique_posters": 23,
    "top_posters": [(1, 142), (2, 98), (3, 76)],
    "top_reaction_receivers": [(2, 47), (3, 31), (4, 22)],
    "most_active_channels": [(10, "general", 312), (11, "gaming", 198), (12, "music", 145)],
    "top_reacted_message": {
        "message_id": 999,
        "channel_id": 10,
        "channel_name": "general",
        "author_id": 5,
        "content": "This is a great message!",
        "reaction_count": 18,
    },
    "new_member_count": 2,
    "active_streak_counts": (14, 5),
    "new_hof_count": 3,
}


def _run_with_patched_queries(cog, guild, overrides=None, vibe_text=None):
    """Run _build_recap_embed with all queries patched via ExitStack."""
    values = {**_DEFAULT_PATCHES, **(overrides or {})}
    vibe = vibe_text or "A high-energy week with lively debates."
    with ExitStack() as stack:
        for name, val in values.items():
            stack.enter_context(
                patch.object(eq, name, new_callable=AsyncMock, return_value=val)
            )
        stack.enter_context(
            patch(
                "gentlebot.cogs.weekly_recap_cog._generate_vibe",
                new_callable=AsyncMock,
                return_value=vibe,
            )
        )
        embed = asyncio.run(cog._build_recap_embed(guild))
    return embed


# ── Tests ──────────────────────────────────────────────────────────────


def test_week_range_title_format():
    """_week_range_title should return a 'Mon DD to Mon DD' string."""
    title = _week_range_title()
    assert " to " in title


def test_delta_str_up():
    """Positive delta should show 'up X%'."""
    # 14-day total = 200, current week = 120, prev week = 80
    result = _delta_str(120, 200)
    assert "up 50%" in result


def test_delta_str_down():
    """Negative delta should show 'down X%'."""
    # 14-day total = 200, current week = 80, prev week = 120
    result = _delta_str(80, 200)
    assert "down" in result


def test_delta_str_zero_prev():
    """Zero previous should return empty string (avoid division by zero)."""
    result = _delta_str(100, 100)
    assert result == ""


def test_delta_str_equal():
    """Equal weeks should return empty string."""
    result = _delta_str(100, 200)
    assert result == ""


def test_build_recap_embed_fields():
    """Embed should have all expected fields and footer."""
    cog = _make_cog(pool=AsyncMock())
    guild = _mock_guild()

    embed = _run_with_patched_queries(cog, guild)

    assert isinstance(embed, discord.Embed)

    field_names = [f.name for f in embed.fields]
    assert "Top Posters" in field_names
    assert "Reaction Magnets" in field_names
    assert "Hot Channels" in field_names
    assert "Message of the Week" in field_names
    assert "Community Pulse" in field_names

    # Footer should tease /mystats
    assert embed.footer and "/mystats" in embed.footer.text

    # Color should be teal
    assert embed.color == discord.Color.teal()


def test_recap_empty_data():
    """Embed should handle zero activity gracefully."""
    cog = _make_cog(pool=AsyncMock())
    guild = _mock_guild()

    empty = {
        "server_message_count": 0,
        "unique_posters": 0,
        "top_posters": [],
        "top_reaction_receivers": [],
        "most_active_channels": [],
        "top_reacted_message": None,
        "new_member_count": 0,
        "active_streak_counts": (0, 0),
        "new_hof_count": 0,
    }

    embed = _run_with_patched_queries(
        cog, guild, overrides=empty,
        vibe_text="Here's what happened in Gentlefolk this week.",
    )

    assert isinstance(embed, discord.Embed)
    # Should still have Community Pulse even when empty
    field_names = [f.name for f in embed.fields]
    assert "Community Pulse" in field_names
    # Should NOT have top posters field when list is empty
    assert "Top Posters" not in field_names


def test_recap_disabled():
    """Feature flag off should prevent scheduler creation."""
    with patch.object(weekly_recap_cog.cfg, "WEEKLY_RECAP_ENABLED", False):
        cog = _make_cog()
        # cog_load should not create a scheduler
        asyncio.run(cog.cog_load())
        assert cog.scheduler is None


def test_recap_idempotent():
    """The _post_recap method should be wrapped by @idempotent_task."""
    # Verify the wrapper exists by checking the function name
    assert hasattr(WeeklyRecapCog, "_post_recap")
    # The idempotent_task decorator preserves the function name via functools.wraps
    assert WeeklyRecapCog._post_recap.__wrapped__.__name__ == "_post_recap"


def test_week_over_week_delta_calculation():
    """Week-over-week delta should compute correctly."""
    # current=150, 14-day total=250 => prev week=100 => delta = +50%
    assert _delta_str(150, 250) == " (up 50%)"
    # current=50, 14-day total=200 => prev week=150 => delta = -67%
    assert "down 67%" in _delta_str(50, 200)


def test_recap_message_of_week_truncation():
    """Long message content should be truncated in the embed."""
    cog = _make_cog(pool=AsyncMock())
    guild = _mock_guild()

    long_msg = {
        "message_id": 999,
        "channel_id": 10,
        "channel_name": "general",
        "author_id": 5,
        "content": "x" * 200,  # Already truncated by SQL to 200 chars
        "reaction_count": 18,
    }

    embed = _run_with_patched_queries(
        cog, guild, overrides={"top_reacted_message": long_msg},
        vibe_text="Test vibe.",
    )

    motw_field = next(f for f in embed.fields if f.name == "Message of the Week")
    # Content should be truncated to ~120 chars + "..."
    assert "..." in motw_field.value


def test_generate_vibe_fallback_on_disabled():
    """Vibe generation should fall back when LLM is disabled."""
    with patch.object(weekly_recap_cog.cfg, "WEEKLY_RECAP_LLM_ENABLED", False):
        result = asyncio.run(weekly_recap_cog._generate_vibe({}, "TestServer"))
    assert "TestServer" in result


def test_generate_vibe_fallback_on_error():
    """Vibe generation should fall back on LLM error."""
    with patch(
        "gentlebot.cogs.weekly_recap_cog.router.generate",
        side_effect=Exception("API error"),
    ):
        result = asyncio.run(weekly_recap_cog._generate_vibe({}, "TestServer"))
    assert "TestServer" in result
