"""Tests for the book enrichment cog."""
import asyncio
import collections
import types
from unittest.mock import MagicMock, patch


def test_search_open_library_returns_none_on_failure():
    """_search_open_library should return None on API failure."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.book_enrichment_cog import BookEnrichmentCog

    cog = BookEnrichmentCog(bot)

    with patch.object(cog.session, "get") as mock_get:
        mock_get.side_effect = Exception("Network error")
        result = cog._search_open_library("Test Book")
        assert result is None


def test_search_open_library_returns_none_on_empty():
    """_search_open_library should return None when no results."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.book_enrichment_cog import BookEnrichmentCog

    cog = BookEnrichmentCog(bot)

    mock_response = MagicMock()
    mock_response.json.return_value = {"docs": []}

    with patch.object(cog.session, "get", return_value=mock_response):
        result = cog._search_open_library("Nonexistent Book 12345")
        assert result is None


def test_search_open_library_parses_response():
    """_search_open_library should parse Open Library response correctly."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.book_enrichment_cog import BookEnrichmentCog

    cog = BookEnrichmentCog(bot)

    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {
        "docs": [
            {
                "key": "/works/OL123W",
                "title": "Test Book",
                "author_name": ["Test Author"],
                "first_publish_year": 2020,
                "number_of_pages_median": 300,
                "subject": ["Fiction", "Adventure"],
                "ratings_average": 4.5,
                "ratings_count": 100,
                "cover_i": 12345,
            }
        ]
    }

    # Mock the work endpoint too
    mock_work_response = MagicMock()
    mock_work_response.ok = True
    mock_work_response.json.return_value = {
        "description": "A test book description."
    }

    with patch.object(cog.session, "get") as mock_get:
        mock_get.side_effect = [mock_response, mock_work_response]
        result = cog._search_open_library("Test Book")

        assert result is not None
        assert result["title"] == "Test Book"
        assert result["authors"] == ["Test Author"]
        assert result["year"] == 2020
        assert result["pages"] == 300
        assert result["rating"] == 4.5


def test_format_book_embed():
    """_format_book_embed should create a valid Discord embed."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.book_enrichment_cog import BookEnrichmentCog

    cog = BookEnrichmentCog(bot)

    book_data = {
        "title": "The Midnight Library",
        "authors": ["Matt Haig"],
        "year": 2020,
        "pages": 288,
        "subjects": ["Fiction", "Fantasy"],
        "rating": 4.2,
        "rating_count": 1500,
        "cover_id": 12345,
        "description": "A beautiful story about life choices.",
        "key": "/works/OL123W",
    }

    embed = cog._format_book_embed(book_data)

    assert embed.title == "📖 The Midnight Library"
    assert embed.url == "https://openlibrary.org/works/OL123W"


def test_cog_disabled_skips_processing():
    """BookEnrichmentCog should skip processing when disabled."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.book_enrichment_cog import BookEnrichmentCog

        cog = BookEnrichmentCog(bot)
        cog.enabled = False
        cog.reading_channel_id = 456

        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=456),
            content="Just finished reading 1984",
        )

        # Should return early without processing
        await cog.on_message(msg)

    asyncio.run(run())


def test_cog_wrong_channel_skips():
    """BookEnrichmentCog should skip messages in wrong channel."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.book_enrichment_cog import BookEnrichmentCog

        cog = BookEnrichmentCog(bot)
        cog.enabled = True
        cog.reading_channel_id = 456

        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=789),  # Different channel
            content="Just finished reading 1984",
        )

        # Should return early without processing
        await cog.on_message(msg)

    asyncio.run(run())


def test_cog_ignores_bot_messages():
    """BookEnrichmentCog should ignore bot messages."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.book_enrichment_cog import BookEnrichmentCog

        cog = BookEnrichmentCog(bot)
        cog.enabled = True
        cog.reading_channel_id = 456

        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=True),
            channel=types.SimpleNamespace(id=456),
            content="Just finished reading 1984",
        )

        # Should return early without processing
        await cog.on_message(msg)

    asyncio.run(run())


def test_book_emoji_constant():
    """BOOK_EMOJI should be the book emoji."""
    from gentlebot.cogs.book_enrichment_cog import BOOK_EMOJI

    assert BOOK_EMOJI == "📚"


def test_dedup_guard_blocks_second_reaction():
    """Second reaction on same message should be blocked by dedup deque."""
    from gentlebot.cogs.book_enrichment_cog import BookEnrichmentCog

    bot = types.SimpleNamespace()
    bot.user = types.SimpleNamespace(id=100)

    cog = BookEnrichmentCog(bot)
    cog.enabled = True

    # Pre-populate the dedup deque
    cog._responded_messages.append(999)

    async def run():
        payload = types.SimpleNamespace(
            emoji="📚",
            user_id=456,
            message_id=999,
            channel_id=789,
        )
        # Should return early without fetching the channel
        await cog.on_raw_reaction_add(payload)

    asyncio.run(run())
    assert 999 in cog._responded_messages


def test_dedup_deque_initialized():
    """BookEnrichmentCog should have _responded_messages deque on init."""
    from gentlebot.cogs.book_enrichment_cog import BookEnrichmentCog

    bot = types.SimpleNamespace()
    cog = BookEnrichmentCog(bot)
    assert isinstance(cog._responded_messages, collections.deque)
    assert cog._responded_messages.maxlen == 500
