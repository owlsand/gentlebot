"""Tests for the Feature Discovery cog."""
import asyncio
import time
import types


def test_long_message_threshold():
    """LONG_MESSAGE_THRESHOLD should be 500 characters."""
    from gentlebot.cogs.feature_discovery_cog import LONG_MESSAGE_THRESHOLD

    assert LONG_MESSAGE_THRESHOLD == 500


def test_spotlight_features_not_empty():
    """SPOTLIGHT_FEATURES should have at least one entry."""
    from gentlebot.cogs.feature_discovery_cog import SPOTLIGHT_FEATURES

    assert len(SPOTLIGHT_FEATURES) >= 1
    for feat in SPOTLIGHT_FEATURES:
        assert "name" in feat
        assert "description" in feat
        assert "example" in feat


def test_tip_definitions_structure():
    """TIP_DEFINITIONS should be a list of (key, message) tuples."""
    from gentlebot.cogs.feature_discovery_cog import TIP_DEFINITIONS

    assert len(TIP_DEFINITIONS) == 4
    keys = {t[0] for t in TIP_DEFINITIONS}
    assert "tldr" in keys
    assert "link_summary" in keys
    assert "book_enrichment" in keys
    assert "vibecheck" in keys


def test_capabilities_registered():
    """FeatureDiscoveryCog should have CAPABILITIES with scheduled task."""
    from gentlebot.cogs.feature_discovery_cog import FeatureDiscoveryCog
    from gentlebot.capabilities import CogCapabilities

    assert hasattr(FeatureDiscoveryCog, "CAPABILITIES")
    assert isinstance(FeatureDiscoveryCog.CAPABILITIES, CogCapabilities)
    assert len(FeatureDiscoveryCog.CAPABILITIES.scheduled) == 1
    assert "Spotlight" in FeatureDiscoveryCog.CAPABILITIES.scheduled[0].name


def test_match_tip_long_message():
    """_match_tip should detect long messages for TL;DR tip."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.feature_discovery_cog import FeatureDiscoveryCog

        cog = FeatureDiscoveryCog(bot)

        msg = types.SimpleNamespace(
            content="A" * 600,
            channel=types.SimpleNamespace(id=789),
        )

        key, text = cog._match_tip(msg)
        assert key == "tldr"
        assert text is not None
        assert "📝" in text

    asyncio.run(run())


def test_match_tip_url():
    """_match_tip should detect URLs for link summary tip."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.feature_discovery_cog import FeatureDiscoveryCog

        cog = FeatureDiscoveryCog(bot)

        msg = types.SimpleNamespace(
            content="Check out https://example.com/article",
            channel=types.SimpleNamespace(id=789),
        )

        key, text = cog._match_tip(msg)
        assert key == "link_summary"
        assert "📋" in text

    asyncio.run(run())


def test_match_tip_skips_image_urls():
    """_match_tip should skip image host URLs."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.feature_discovery_cog import FeatureDiscoveryCog

        cog = FeatureDiscoveryCog(bot)

        msg = types.SimpleNamespace(
            content="Look at this https://i.imgur.com/abc.png",
            channel=types.SimpleNamespace(id=789),
        )

        key, text = cog._match_tip(msg)
        assert key is None
        assert text is None

    asyncio.run(run())


def test_match_tip_activity_question():
    """_match_tip should detect activity questions for vibecheck tip."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.feature_discovery_cog import FeatureDiscoveryCog

        cog = FeatureDiscoveryCog(bot)

        msg = types.SimpleNamespace(
            content="how active has the server been?",
            channel=types.SimpleNamespace(id=789),
        )

        key, text = cog._match_tip(msg)
        assert key == "vibecheck"
        assert "/vibecheck" in text

    asyncio.run(run())


def test_match_tip_short_message_no_match():
    """_match_tip should return None for short plain messages."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.feature_discovery_cog import FeatureDiscoveryCog

        cog = FeatureDiscoveryCog(bot)

        msg = types.SimpleNamespace(
            content="hey what's up",
            channel=types.SimpleNamespace(id=789),
        )

        key, text = cog._match_tip(msg)
        assert key is None
        assert text is None

    asyncio.run(run())


def test_channel_tip_cooldown_constant():
    """Channel tip cooldown should be 24 hours in seconds."""
    from gentlebot.cogs.feature_discovery_cog import _CHANNEL_TIP_COOLDOWN

    assert _CHANNEL_TIP_COOLDOWN == 86400


def test_extract_domain():
    """_extract_domain should strip protocol, www, and path."""
    from gentlebot.cogs.feature_discovery_cog import _extract_domain

    assert _extract_domain("https://www.example.com/path") == "example.com"
    assert _extract_domain("http://cdn.discordapp.com/img.png") == "cdn.discordapp.com"
    assert _extract_domain("https://i.imgur.com/abc.jpg") == "i.imgur.com"


def test_on_message_skips_bot():
    """on_message should skip bot messages."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.feature_discovery_cog import FeatureDiscoveryCog

        cog = FeatureDiscoveryCog(bot)
        cog.pool = types.SimpleNamespace()  # Simulate pool present

        msg = types.SimpleNamespace(
            id=456,
            author=types.SimpleNamespace(bot=True),
            guild=types.SimpleNamespace(id=999),
            content="A" * 600,
        )

        # Should return early without error
        await cog.on_message(msg)

    asyncio.run(run())


def test_on_message_skips_dm():
    """on_message should skip DMs (guild=None)."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.feature_discovery_cog import FeatureDiscoveryCog

        cog = FeatureDiscoveryCog(bot)
        cog.pool = types.SimpleNamespace()

        msg = types.SimpleNamespace(
            id=456,
            author=types.SimpleNamespace(bot=False),
            guild=None,
            content="A" * 600,
        )

        await cog.on_message(msg)

    asyncio.run(run())
