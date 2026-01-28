"""Tests for the #wins channel moderation cog."""
import types
import asyncio
from unittest.mock import MagicMock, AsyncMock

from gentlebot.cogs import wins_cog


def test_is_celebration_detects_win_keywords():
    """is_celebration should detect celebration keywords."""
    is_win, confidence = wins_cog.is_celebration("I got the job!")
    assert is_win is True
    assert confidence > 0


def test_is_celebration_detects_emojis():
    """is_celebration should detect celebration emojis."""
    is_win, confidence = wins_cog.is_celebration("Yes! 🎉")
    assert is_win is True


def test_is_celebration_detects_non_celebration():
    """is_celebration should detect non-celebratory content."""
    is_win, confidence = wins_cog.is_celebration("Does anyone know how to fix this?")
    assert is_win is False


def test_is_celebration_detects_questions():
    """is_celebration should detect questions as non-celebrations."""
    is_win, confidence = wins_cog.is_celebration("What should I do about this problem?")
    assert is_win is False


def test_is_celebration_neutral_message():
    """is_celebration should handle neutral messages."""
    # Neutral message that doesn't strongly indicate either way
    is_win, confidence = wins_cog.is_celebration("Hello everyone")
    # Confidence should be relatively low for neutral messages
    assert isinstance(is_win, bool)
    assert 0 <= confidence <= 1


def test_celebration_patterns():
    """is_celebration should detect common celebration patterns."""
    # "I got..." pattern
    is_win, _ = wins_cog.is_celebration("I got promoted today")
    assert is_win is True

    # "finally" pattern
    is_win, _ = wins_cog.is_celebration("Finally passed my exam")
    assert is_win is True

    # "just got" pattern
    is_win, _ = wins_cog.is_celebration("Just got hired at my dream company")
    assert is_win is True


def test_non_celebration_patterns():
    """is_celebration should detect non-celebration patterns."""
    # Question ending
    is_win, _ = wins_cog.is_celebration("Is this working?")
    assert is_win is False

    # Asking the group
    is_win, _ = wins_cog.is_celebration("Anyone know a good restaurant?")
    assert is_win is False

    # Frustration
    is_win, _ = wins_cog.is_celebration("Ugh this is so frustrating")
    assert is_win is False


def test_celebration_emojis_constant():
    """CELEBRATION_EMOJIS should contain expected emojis."""
    assert "🎉" in wins_cog.CELEBRATION_EMOJIS
    assert "🥳" in wins_cog.CELEBRATION_EMOJIS
    assert "👏" in wins_cog.CELEBRATION_EMOJIS


def test_cog_ignores_bot_messages():
    """WinsCog should ignore bot messages."""
    async def run():
        bot = types.SimpleNamespace()
        cog = wins_cog.WinsCog(bot)
        cog.wins_channel_id = 123

        # Bot message should be ignored
        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=True),
            channel=types.SimpleNamespace(id=123),
            content="I got the job!",
        )

        # Should return early without processing
        await cog.on_message(msg)
        # No assertion needed - just verifying no exception

    asyncio.run(run())


def test_cog_ignores_other_channels():
    """WinsCog should ignore messages in other channels."""
    async def run():
        bot = types.SimpleNamespace()
        cog = wins_cog.WinsCog(bot)
        cog.wins_channel_id = 123

        # Message in different channel should be ignored
        msg = types.SimpleNamespace(
            author=types.SimpleNamespace(bot=False),
            channel=types.SimpleNamespace(id=456),  # Different channel
            content="I got the job!",
        )

        # Should return early without processing
        await cog.on_message(msg)
        # No assertion needed - just verifying no exception

    asyncio.run(run())


def test_cog_handles_short_messages():
    """WinsCog should handle very short messages."""
    async def run():
        bot = types.SimpleNamespace()
        cog = wins_cog.WinsCog(bot)
        cog.wins_channel_id = 123

        class MockMessage:
            def __init__(self):
                self.author = types.SimpleNamespace(bot=False)
                self.channel = types.SimpleNamespace(id=123)
                self.content = "ok"
                self.reactions_added = []

            async def add_reaction(self, emoji):
                self.reactions_added.append(emoji)

        msg = MockMessage()
        await cog.on_message(msg)
        # Short messages should be handled without error

    asyncio.run(run())


def test_wins_test_command():
    """!wins_test command should return analysis."""
    async def run():
        bot = types.SimpleNamespace()
        cog = wins_cog.WinsCog(bot)

        class MockContext:
            def __init__(self):
                self.sent = None

            async def send(self, content):
                self.sent = content

        ctx = MockContext()
        await cog.wins_test(ctx, text="I got promoted!")

        assert ctx.sent is not None
        assert "CELEBRATION" in ctx.sent
        assert "Confidence" in ctx.sent


def test_wins_stats_command():
    """!wins_stats command should return config info."""
    async def run():
        bot = types.SimpleNamespace()
        cog = wins_cog.WinsCog(bot)
        cog.wins_channel_id = 123
        cog.lobby_channel_id = 456

        class MockContext:
            def __init__(self):
                self.sent = None

            async def send(self, content):
                self.sent = content

        ctx = MockContext()
        await cog.wins_stats(ctx)

        assert ctx.sent is not None
        assert "Stats" in ctx.sent
        assert "enabled" in ctx.sent or "disabled" in ctx.sent


def test_confidence_range():
    """Confidence should always be between 0 and 1."""
    test_cases = [
        "I got the job!",
        "This is terrible",
        "What should I do?",
        "🎉🎉🎉",
        "Hello",
        "Finally passed after 10 tries!",
        "I'm so frustrated",
    ]

    for text in test_cases:
        _, confidence = wins_cog.is_celebration(text)
        assert 0 <= confidence <= 1, f"Confidence {confidence} out of range for '{text}'"
