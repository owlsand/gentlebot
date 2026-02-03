"""Tests for the Hall of Fame cog."""
import asyncio
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_cog_initializes_with_disabled_scheduler():
    """HallOfFameCog should initialize with scheduler as None."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.hall_of_fame_cog import HallOfFameCog

    cog = HallOfFameCog(bot)
    assert cog.scheduler is None
    assert cog.pool is None


def test_config_defaults_exist():
    """Hall of Fame config values should have sensible defaults."""
    from gentlebot import bot_config as cfg

    assert hasattr(cfg, "HALL_OF_FAME_ENABLED")
    assert hasattr(cfg, "HALL_OF_FAME_CHANNEL_ID")
    assert hasattr(cfg, "HOF_NOMINATION_THRESHOLD")
    assert hasattr(cfg, "HOF_VOTE_THRESHOLD")
    assert hasattr(cfg, "HOF_EMOJI")

    # Check default threshold values
    assert cfg.HOF_NOMINATION_THRESHOLD >= 1
    assert cfg.HOF_VOTE_THRESHOLD >= 1
    assert cfg.HOF_EMOJI == "\U0001f3c6"  # Trophy emoji


def test_capabilities_declared():
    """HallOfFameCog should declare CAPABILITIES."""
    from gentlebot.cogs.hall_of_fame_cog import HallOfFameCog
    from gentlebot.capabilities import CogCapabilities

    assert hasattr(HallOfFameCog, "CAPABILITIES")
    assert isinstance(HallOfFameCog.CAPABILITIES, CogCapabilities)

    # Should have reaction capability for trophy emoji
    assert len(HallOfFameCog.CAPABILITIES.reactions) >= 1
    assert any(
        r.emoji == "\U0001f3c6" for r in HallOfFameCog.CAPABILITIES.reactions
    )

    # Should have scheduled capability for nomination checks
    assert len(HallOfFameCog.CAPABILITIES.scheduled) >= 1


def test_check_nominations_no_pool():
    """_check_nominations should handle missing pool gracefully."""
    bot = types.SimpleNamespace()
    from gentlebot.cogs.hall_of_fame_cog import HallOfFameCog

    cog = HallOfFameCog(bot)
    cog.pool = None

    async def run():
        # Should return None without error due to @require_pool
        result = await cog._check_nominations()
        return result

    result = asyncio.run(run())
    assert result is None


def test_on_raw_reaction_add_ignores_non_trophy():
    """on_raw_reaction_add should ignore non-trophy reactions."""
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 12345
    from gentlebot.cogs.hall_of_fame_cog import HallOfFameCog

    cog = HallOfFameCog(bot)
    cog.pool = MagicMock()  # Has pool

    payload = MagicMock()
    payload.emoji = MagicMock()
    payload.emoji.__str__ = MagicMock(return_value="\u2764\ufe0f")  # Heart, not trophy
    payload.user_id = 99999
    payload.guild_id = 11111

    async def run():
        # Mock pool.fetchrow to track if it was called
        cog.pool.fetchrow = AsyncMock(return_value=None)

        with patch("gentlebot.cogs.hall_of_fame_cog.cfg") as mock_cfg:
            mock_cfg.HALL_OF_FAME_ENABLED = True
            mock_cfg.HOF_EMOJI = "\U0001f3c6"
            await cog.on_raw_reaction_add(payload)

        # Should not query database for non-trophy emoji
        cog.pool.fetchrow.assert_not_called()

    asyncio.run(run())


def test_on_raw_reaction_add_ignores_bot_reactions():
    """on_raw_reaction_add should ignore the bot's own reactions."""
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 12345
    from gentlebot.cogs.hall_of_fame_cog import HallOfFameCog

    cog = HallOfFameCog(bot)
    cog.pool = MagicMock()

    payload = MagicMock()
    payload.emoji = MagicMock()
    payload.emoji.__str__ = MagicMock(return_value="\U0001f3c6")  # Trophy
    payload.user_id = 12345  # Same as bot
    payload.guild_id = 11111

    async def run():
        cog.pool.fetchrow = AsyncMock(return_value=None)

        with patch("gentlebot.cogs.hall_of_fame_cog.cfg") as mock_cfg:
            mock_cfg.HALL_OF_FAME_ENABLED = True
            mock_cfg.HOF_EMOJI = "\U0001f3c6"
            await cog.on_raw_reaction_add(payload)

        # Should not query database for bot's own reaction
        cog.pool.fetchrow.assert_not_called()

    asyncio.run(run())


def test_on_raw_reaction_add_ignores_dms():
    """on_raw_reaction_add should ignore DM reactions."""
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 12345
    from gentlebot.cogs.hall_of_fame_cog import HallOfFameCog

    cog = HallOfFameCog(bot)
    cog.pool = MagicMock()

    payload = MagicMock()
    payload.emoji = MagicMock()
    payload.emoji.__str__ = MagicMock(return_value="\U0001f3c6")
    payload.user_id = 99999
    payload.guild_id = None  # DM

    async def run():
        cog.pool.fetchrow = AsyncMock(return_value=None)

        with patch("gentlebot.cogs.hall_of_fame_cog.cfg") as mock_cfg:
            mock_cfg.HALL_OF_FAME_ENABLED = True
            mock_cfg.HOF_EMOJI = "\U0001f3c6"
            await cog.on_raw_reaction_add(payload)

        # Should not query database for DM reactions
        cog.pool.fetchrow.assert_not_called()

    asyncio.run(run())


def test_on_raw_reaction_add_ignores_non_nominated():
    """on_raw_reaction_add should ignore reactions on non-nominated messages."""
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 12345
    from gentlebot.cogs.hall_of_fame_cog import HallOfFameCog

    cog = HallOfFameCog(bot)
    cog.pool = MagicMock()

    payload = MagicMock()
    payload.emoji = MagicMock()
    payload.emoji.__str__ = MagicMock(return_value="\U0001f3c6")
    payload.user_id = 99999
    payload.guild_id = 11111
    payload.message_id = 55555

    async def run():
        # Return None = message not in hall_of_fame table
        cog.pool.fetchrow = AsyncMock(return_value=None)
        cog.pool.execute = AsyncMock()

        with patch("gentlebot.cogs.hall_of_fame_cog.cfg") as mock_cfg:
            mock_cfg.HALL_OF_FAME_ENABLED = True
            mock_cfg.HOF_EMOJI = "\U0001f3c6"
            await cog.on_raw_reaction_add(payload)

        # Should query but not update (no nomination found)
        cog.pool.fetchrow.assert_called_once()
        cog.pool.execute.assert_not_called()

    asyncio.run(run())


def test_on_raw_reaction_add_ignores_already_inducted():
    """on_raw_reaction_add should ignore reactions on already inducted messages."""
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 12345
    from gentlebot.cogs.hall_of_fame_cog import HallOfFameCog
    from datetime import datetime

    cog = HallOfFameCog(bot)
    cog.pool = MagicMock()

    payload = MagicMock()
    payload.emoji = MagicMock()
    payload.emoji.__str__ = MagicMock(return_value="\U0001f3c6")
    payload.user_id = 99999
    payload.guild_id = 11111
    payload.message_id = 55555

    async def run():
        # Return row with inducted_at set (already inducted)
        cog.pool.fetchrow = AsyncMock(
            return_value={
                "entry_id": 1,
                "vote_count": 5,
                "inducted_at": datetime.now(),  # Already inducted
                "channel_id": 22222,
                "author_id": 33333,
            }
        )
        cog.pool.execute = AsyncMock()

        with patch("gentlebot.cogs.hall_of_fame_cog.cfg") as mock_cfg:
            mock_cfg.HALL_OF_FAME_ENABLED = True
            mock_cfg.HOF_EMOJI = "\U0001f3c6"
            await cog.on_raw_reaction_add(payload)

        # Should query but not update (already inducted)
        cog.pool.fetchrow.assert_called_once()
        cog.pool.execute.assert_not_called()

    asyncio.run(run())


def test_on_raw_reaction_add_increments_vote():
    """on_raw_reaction_add should increment vote_count for nominated messages."""
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 12345
    from gentlebot.cogs.hall_of_fame_cog import HallOfFameCog

    cog = HallOfFameCog(bot)
    cog.pool = MagicMock()

    payload = MagicMock()
    payload.emoji = MagicMock()
    payload.emoji.__str__ = MagicMock(return_value="\U0001f3c6")
    payload.user_id = 99999
    payload.guild_id = 11111
    payload.message_id = 55555

    async def run():
        # Return row with vote_count = 1, threshold = 3 (not yet inducted)
        cog.pool.fetchrow = AsyncMock(
            return_value={
                "entry_id": 1,
                "vote_count": 1,
                "inducted_at": None,  # Not inducted
                "channel_id": 22222,
                "author_id": 33333,
            }
        )
        cog.pool.execute = AsyncMock()

        with patch("gentlebot.cogs.hall_of_fame_cog.cfg") as mock_cfg:
            mock_cfg.HALL_OF_FAME_ENABLED = True
            mock_cfg.HOF_EMOJI = "\U0001f3c6"
            mock_cfg.HOF_VOTE_THRESHOLD = 3
            await cog.on_raw_reaction_add(payload)

        # Should update vote count (1 -> 2, still below threshold)
        cog.pool.execute.assert_called_once()
        call_args = cog.pool.execute.call_args
        assert "UPDATE" in call_args[0][0]
        assert call_args[0][1] == 2  # new vote_count

    asyncio.run(run())


def test_on_raw_message_delete_removes_nomination():
    """on_raw_message_delete should remove non-inducted nominations."""
    bot = MagicMock()
    from gentlebot.cogs.hall_of_fame_cog import HallOfFameCog

    cog = HallOfFameCog(bot)
    cog.pool = MagicMock()

    payload = MagicMock()
    payload.message_id = 55555

    async def run():
        cog.pool.execute = AsyncMock(return_value="DELETE 1")

        with patch("gentlebot.cogs.hall_of_fame_cog.cfg") as mock_cfg:
            mock_cfg.HALL_OF_FAME_ENABLED = True
            await cog.on_raw_message_delete(payload)

        # Should attempt to delete nomination
        cog.pool.execute.assert_called_once()
        call_args = cog.pool.execute.call_args
        assert "DELETE" in call_args[0][0]
        assert "inducted_at IS NULL" in call_args[0][0]

    asyncio.run(run())


def test_feature_disabled_skips_processing():
    """When HALL_OF_FAME_ENABLED is False, handlers should skip processing."""
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 12345
    from gentlebot.cogs.hall_of_fame_cog import HallOfFameCog

    cog = HallOfFameCog(bot)
    cog.pool = MagicMock()

    payload = MagicMock()
    payload.emoji = MagicMock()
    payload.emoji.__str__ = MagicMock(return_value="\U0001f3c6")
    payload.user_id = 99999
    payload.guild_id = 11111
    payload.message_id = 55555

    async def run():
        cog.pool.fetchrow = AsyncMock()

        with patch("gentlebot.cogs.hall_of_fame_cog.cfg") as mock_cfg:
            mock_cfg.HALL_OF_FAME_ENABLED = False  # Disabled
            mock_cfg.HOF_EMOJI = "\U0001f3c6"
            await cog.on_raw_reaction_add(payload)

        # Should not query database when feature is disabled
        cog.pool.fetchrow.assert_not_called()

    asyncio.run(run())
