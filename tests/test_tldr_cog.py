"""Tests for the TL;DR cog."""
import asyncio
import collections
import types
from unittest.mock import AsyncMock, MagicMock, patch


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


def test_dedup_guard_blocks_second_reaction():
    """Second reaction on same message should be blocked by dedup deque."""
    from gentlebot.cogs.tldr_cog import TLDRCog

    bot = types.SimpleNamespace()
    bot.user = types.SimpleNamespace(id=100)

    cog = TLDRCog(bot)
    cog.enabled = True

    # Pre-populate the dedup deque
    cog._responded_messages.append(999)

    async def run():
        payload = types.SimpleNamespace(
            emoji="📝",
            user_id=456,
            message_id=999,
            channel_id=789,
        )
        # Should return early without fetching the channel
        await cog.on_raw_reaction_add(payload)

    asyncio.run(run())
    # Deque should still contain the message (not removed)
    assert 999 in cog._responded_messages


def test_dedup_deque_initialized():
    """TLDRCog should have _responded_messages deque on init."""
    from gentlebot.cogs.tldr_cog import TLDRCog

    bot = types.SimpleNamespace()
    cog = TLDRCog(bot)
    assert isinstance(cog._responded_messages, collections.deque)
    assert cog._responded_messages.maxlen == 500


def test_error_summary_returns_empty():
    """_summarize_message should return empty string on LLM failure."""
    from gentlebot.cogs.tldr_cog import TLDRCog

    bot = types.SimpleNamespace()
    cog = TLDRCog(bot)

    async def run():
        with patch("gentlebot.cogs.tldr_cog.router") as mock_router:
            mock_router.generate.side_effect = Exception("LLM down")
            result = await cog._summarize_message("test content", "TestUser")
            assert result == ""

    asyncio.run(run())
