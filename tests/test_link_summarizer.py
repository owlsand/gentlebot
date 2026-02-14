"""Tests for the link summarizer cog."""
import asyncio
import types
from unittest.mock import MagicMock, patch


def test_extract_domain():
    """_extract_domain should extract domain from URL."""
    from gentlebot.cogs.link_summarizer_cog import _extract_domain

    assert _extract_domain("https://example.com/path") == "example.com"
    assert _extract_domain("https://www.example.com/path") == "example.com"
    assert _extract_domain("http://sub.example.com/page.html") == "sub.example.com"


def test_should_skip_url_skips_image_hosts():
    """_should_skip_url should skip image/GIF hosts."""
    from gentlebot.cogs.link_summarizer_cog import _should_skip_url

    assert _should_skip_url("https://tenor.com/view/123") is True
    assert _should_skip_url("https://giphy.com/gifs/abc") is True
    assert _should_skip_url("https://imgur.com/gallery/xyz") is True
    assert _should_skip_url("https://i.imgur.com/abc.gif") is True


def test_should_skip_url_allows_normal_urls():
    """_should_skip_url should allow normal URLs."""
    from gentlebot.cogs.link_summarizer_cog import _should_skip_url

    assert _should_skip_url("https://nytimes.com/article") is False
    assert _should_skip_url("https://github.com/repo") is False
    assert _should_skip_url("https://twitter.com/status/123") is False


def test_url_pattern_matches():
    """URL_PATTERN should match http/https URLs."""
    from gentlebot.cogs.link_summarizer_cog import URL_PATTERN

    text = "Check out https://example.com/page and http://test.org"
    matches = URL_PATTERN.findall(text)
    assert len(matches) == 2
    assert "https://example.com/page" in matches
    assert "http://test.org" in matches


def test_url_pattern_no_match():
    """URL_PATTERN should not match non-URLs."""
    from gentlebot.cogs.link_summarizer_cog import URL_PATTERN

    text = "Just some text without links"
    matches = URL_PATTERN.findall(text)
    assert len(matches) == 0


def test_fetch_page_content_handles_failure():
    """_fetch_page_content should return None on failure."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.link_summarizer_cog import LinkSummarizerCog

    cog = LinkSummarizerCog(bot)

    with patch.object(cog.session, "get") as mock_get:
        mock_get.side_effect = Exception("Network error")
        result = cog._fetch_page_content("https://example.com")
        assert result is None


def test_cog_disabled_skips_processing():
    """LinkSummarizerCog should skip processing when disabled."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.link_summarizer_cog import LinkSummarizerCog

        cog = LinkSummarizerCog(bot)
        cog.enabled = False

        msg = types.SimpleNamespace(
            id=456,
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=789),
            content="Check out https://example.com",
        )

        # Should return early without processing
        await cog.on_message(msg)

    asyncio.run(run())


def test_cog_ignores_bot_messages():
    """LinkSummarizerCog should ignore bot messages."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.link_summarizer_cog import LinkSummarizerCog

        cog = LinkSummarizerCog(bot)
        cog.enabled = True

        msg = types.SimpleNamespace(
            id=456,
            author=types.SimpleNamespace(bot=True),
            channel=types.SimpleNamespace(id=789),
            content="Check out https://example.com",
        )

        # Should return early without processing
        await cog.on_message(msg)

    asyncio.run(run())


def test_cog_ignores_messages_without_urls():
    """LinkSummarizerCog should ignore messages without URLs."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.link_summarizer_cog import LinkSummarizerCog

        cog = LinkSummarizerCog(bot)
        cog.enabled = True

        msg = types.SimpleNamespace(
            id=456,
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=789),
            content="Just a regular message",
        )

        # Should return early without processing
        await cog.on_message(msg)

    asyncio.run(run())


def test_summary_emoji_constant():
    """SUMMARY_EMOJI should be the clipboard emoji."""
    from gentlebot.cogs.link_summarizer_cog import SUMMARY_EMOJI

    assert SUMMARY_EMOJI == "📋"


def test_skip_domains_contains_expected():
    """SKIP_DOMAINS should contain image/GIF hosts."""
    from gentlebot.cogs.link_summarizer_cog import SKIP_DOMAINS

    assert "tenor.com" in SKIP_DOMAINS
    assert "giphy.com" in SKIP_DOMAINS
    assert "imgur.com" in SKIP_DOMAINS
    assert "klipy.com" in SKIP_DOMAINS


def test_should_skip_url_klipy():
    """_should_skip_url should skip klipy.com embed URLs."""
    from gentlebot.cogs.link_summarizer_cog import _should_skip_url

    assert _should_skip_url("https://klipy.com/embed/abc") is True


def test_should_skip_url_gif_extension():
    """_should_skip_url should skip URLs ending with .gif."""
    from gentlebot.cogs.link_summarizer_cog import _should_skip_url

    assert _should_skip_url("https://example.com/funny.gif") is True


def test_should_skip_url_media_with_query_string():
    """_should_skip_url should skip media URLs even with query strings."""
    from gentlebot.cogs.link_summarizer_cog import _should_skip_url

    assert _should_skip_url("https://example.com/photo.jpg?w=500") is True


def test_should_skip_url_normal_article():
    """_should_skip_url should NOT skip normal article URLs."""
    from gentlebot.cogs.link_summarizer_cog import _should_skip_url

    assert _should_skip_url("https://nytimes.com/article") is False


def test_summarize_content_returns_empty_on_llm_failure():
    """_summarize_content should return empty string on LLM failure."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.link_summarizer_cog import LinkSummarizerCog

    cog = LinkSummarizerCog(bot)

    async def run():
        with patch("gentlebot.cogs.link_summarizer_cog.router") as mock_router:
            mock_router.generate.side_effect = Exception("LLM down")
            result = await cog._summarize_content("https://example.com", "some content")
            assert result == ""

    asyncio.run(run())


def test_summarize_content_returns_empty_on_rate_limit():
    """_summarize_content should return empty string on rate limit."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.link_summarizer_cog import LinkSummarizerCog
    from gentlebot.infra import RateLimited

    cog = LinkSummarizerCog(bot)

    async def run():
        with patch("gentlebot.cogs.link_summarizer_cog.router") as mock_router:
            mock_router.generate.side_effect = RateLimited("general")
            result = await cog._summarize_content("https://example.com", "some content")
            assert result == ""

    asyncio.run(run())
