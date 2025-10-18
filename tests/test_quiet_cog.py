"""Unit tests for the quiet server cog helpers."""

from __future__ import annotations

from types import SimpleNamespace

from gentlebot.cogs.quiet_cog import QuietServerCog


def _make_cog() -> QuietServerCog:
    bot = SimpleNamespace()
    return QuietServerCog(bot)  # type: ignore[arg-type]


def test_select_most_active_channel_prefers_highest_count() -> None:
    cog = _make_cog()
    counts = {111: 5, 222: 8, 333: 8}
    assert cog._select_most_active_channel(counts) == 222
    assert cog._select_most_active_channel({}) is None


def test_should_trigger_only_on_transition() -> None:
    cog = _make_cog()
    assert cog._should_trigger(5) is True
    assert cog._should_trigger(3) is False
    assert cog._should_trigger(12) is False
    assert cog._should_trigger(9) is True
    assert cog._should_trigger(10) is False
