"""Tests for the /celebrate command cog."""
import asyncio
import types
from unittest.mock import MagicMock, patch


def test_fallback_message_with_reason():
    """_fallback_message should include the reason in the message."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.celebrate_cog import CelebrateCog

    cog = CelebrateCog(bot)
    cog.pool = None

    message = cog._fallback_message("Alice", "getting a promotion")
    assert "Alice" in message
    assert "promotion" in message


def test_fallback_message_without_reason():
    """_fallback_message should generate a celebration without a reason."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.celebrate_cog import CelebrateCog

    cog = CelebrateCog(bot)
    cog.pool = None

    message = cog._fallback_message("Bob", None)
    assert "Bob" in message


def test_fallback_message_contains_emojis():
    """_fallback_message should contain celebration emojis."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.celebrate_cog import CelebrateCog, CELEBRATION_EMOJIS

    cog = CelebrateCog(bot)
    cog.pool = None

    message = cog._fallback_message("Charlie", None)
    # Should have at least one celebration emoji
    assert any(emoji in message for emoji in CELEBRATION_EMOJIS)


def test_giphy_gifs_no_api_key():
    """_fetch_giphy_gifs should return empty list when no API key is configured."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.celebrate_cog import CelebrateCog

    cog = CelebrateCog(bot)
    cog.pool = None

    with patch("gentlebot.cogs.celebrate_cog.GIPHY_API_KEY", ""):
        result = cog._fetch_giphy_gifs("celebrate", limit=3)
        assert result == []


def test_giphy_gifs_successful_fetch():
    """_fetch_giphy_gifs should parse Giphy API response correctly."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.celebrate_cog import CelebrateCog

    cog = CelebrateCog(bot)
    cog.pool = None

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"images": {"downsized": {"url": "https://media.giphy.com/gif1.gif"}}},
            {"images": {"downsized": {"url": "https://media.giphy.com/gif2.gif"}}},
        ]
    }

    with patch("gentlebot.cogs.celebrate_cog.GIPHY_API_KEY", "test-key"):
        with patch.object(cog.session, "get", return_value=mock_response):
            result = cog._fetch_giphy_gifs("celebrate", limit=2)
            assert len(result) == 2
            assert all("giphy.com" in url for url in result)


def test_generate_celebration_message_llm_disabled():
    """_generate_celebration_message should use fallback when LLM is disabled."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.celebrate_cog import CelebrateCog

    cog = CelebrateCog(bot)
    cog.pool = None
    cog.llm_enabled = False

    async def run():
        message = await cog._generate_celebration_message(
            "Charlie", "finishing the project", "Dave"
        )
        return message

    message = asyncio.run(run())
    assert "Charlie" in message


def test_record_celebration_no_pool():
    """_record_celebration should not raise when pool is None."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.celebrate_cog import CelebrateCog

    cog = CelebrateCog(bot)
    cog.pool = None

    async def run():
        # Should complete without error
        await cog._record_celebration(
            celebrated_user_id=123,
            celebrated_by_user_id=456,
            reason="test",
            channel_id=789,
            message_id=101112,
        )

    asyncio.run(run())


def test_celebration_search_terms():
    """CELEBRATION_SEARCH_TERMS should contain various celebration terms."""
    from gentlebot.cogs.celebrate_cog import CELEBRATION_SEARCH_TERMS

    assert "celebrate" in CELEBRATION_SEARCH_TERMS
    assert "congratulations" in CELEBRATION_SEARCH_TERMS
    assert len(CELEBRATION_SEARCH_TERMS) >= 5


def test_celebration_emojis():
    """CELEBRATION_EMOJIS should contain expected emojis."""
    from gentlebot.cogs.celebrate_cog import CELEBRATION_EMOJIS

    assert "🎉" in CELEBRATION_EMOJIS
    assert "🥳" in CELEBRATION_EMOJIS
    assert "👏" in CELEBRATION_EMOJIS
    assert len(CELEBRATION_EMOJIS) >= 10
