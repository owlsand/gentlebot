"""Tests for the TL;DR cog."""
import asyncio
import types


def test_tldr_emoji_constant():
    """TLDR_EMOJI should be the memo emoji."""
    from gentlebot.cogs.tldr_cog import TLDR_EMOJI

    assert TLDR_EMOJI == "📝"


def test_default_min_length():
    """DEFAULT_MIN_LENGTH should be 500 characters."""
    from gentlebot.cogs.tldr_cog import DEFAULT_MIN_LENGTH

    assert DEFAULT_MIN_LENGTH == 500


def test_cog_disabled_skips_processing():
    """TLDRCog should skip processing when disabled."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.tldr_cog import TLDRCog

        cog = TLDRCog(bot)
        cog.enabled = False

        msg = types.SimpleNamespace(
            id=456,
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=789),
            content="A" * 600,  # Long enough message
        )

        # Should return early without processing
        await cog.on_message(msg)

    asyncio.run(run())


def test_cog_ignores_bot_messages():
    """TLDRCog should ignore bot messages."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.tldr_cog import TLDRCog

        cog = TLDRCog(bot)
        cog.enabled = True

        msg = types.SimpleNamespace(
            id=456,
            author=types.SimpleNamespace(bot=True),
            channel=types.SimpleNamespace(id=789),
            content="A" * 600,  # Long enough message
        )

        # Should return early without processing
        await cog.on_message(msg)

    asyncio.run(run())


def test_cog_ignores_short_messages():
    """TLDRCog should ignore messages below minimum length."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.tldr_cog import TLDRCog

        cog = TLDRCog(bot)
        cog.enabled = True
        cog.min_length = 500

        msg = types.SimpleNamespace(
            id=456,
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=789),
            content="Short message",  # Below threshold
        )

        # Should return early without processing
        await cog.on_message(msg)

    asyncio.run(run())


def test_capabilities_registered():
    """TLDRCog should have CAPABILITIES with reaction."""
    from gentlebot.cogs.tldr_cog import TLDRCog
    from gentlebot.capabilities import CogCapabilities

    assert hasattr(TLDRCog, "CAPABILITIES")
    assert isinstance(TLDRCog.CAPABILITIES, CogCapabilities)
    assert len(TLDRCog.CAPABILITIES.reactions) == 1
    assert TLDRCog.CAPABILITIES.reactions[0].emoji == "📝"
    assert TLDRCog.CAPABILITIES.reactions[0].trigger == "Long messages"


def test_max_cache_size():
    """MAX_CACHE_SIZE should be defined."""
    from gentlebot.cogs.tldr_cog import MAX_CACHE_SIZE

    assert MAX_CACHE_SIZE == 200
