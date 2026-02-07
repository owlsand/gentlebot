"""Tests for infrastructure modules."""
from __future__ import annotations

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gentlebot.infra import (
    ArchiveConfig,
    CogConfig,
    LLMConfig,
    PoolAwareCog,
    ReactionConfig,
    get_config,
    get_logger,
    log_errors,
    require_pool,
    reset_config,
    set_config,
)
from gentlebot.infra.logging import LogContext, get_cog_logger, structured_log


# --- Logging Tests ---


def test_get_logger_with_name() -> None:
    """get_logger returns a logger with gentlebot prefix."""
    logger = get_logger("my_module")
    assert logger.name == "gentlebot.my_module"


def test_get_logger_without_name() -> None:
    """get_logger without name returns root gentlebot logger."""
    logger = get_logger()
    assert logger.name == "gentlebot"


def test_get_logger_avoids_double_prefix() -> None:
    """get_logger removes existing gentlebot prefix to avoid duplication."""
    logger = get_logger("gentlebot.cogs.my_cog")
    assert logger.name == "gentlebot.cogs.my_cog"


def test_get_cog_logger() -> None:
    """get_cog_logger returns logger under cogs namespace."""
    logger = get_cog_logger("MyCog")
    assert logger.name == "gentlebot.cogs.MyCog"


def test_structured_log(caplog: pytest.LogCaptureFixture) -> None:
    """structured_log appends key=value pairs to message."""
    logger = get_logger("test_structured")
    with caplog.at_level(logging.INFO):
        structured_log(logger, logging.INFO, "Test message", user_id=123, action="test")
    assert "Test message user_id=123 action=test" in caplog.text


# --- Configuration Tests ---


def test_llm_config_defaults() -> None:
    """LLMConfig has sensible defaults."""
    config = LLMConfig()
    assert config.max_tokens == 150
    assert config.temperature == 0.6
    assert config.cooldown_seconds == 10
    assert config.max_prompt_length == 750


def test_llm_config_from_env() -> None:
    """LLMConfig.from_env reads from environment variables."""
    with patch.dict(os.environ, {"LLM_MAX_TOKENS": "200", "LLM_TEMPERATURE": "0.8"}):
        config = LLMConfig.from_env()
        assert config.max_tokens == 200
        assert config.temperature == 0.8


def test_reaction_config_defaults() -> None:
    """ReactionConfig has expected defaults."""
    config = ReactionConfig()
    assert config.base_chance == 0.02
    assert config.mention_chance == 0.25
    assert len(config.default_emojis) > 0


def test_archive_config_from_env() -> None:
    """ArchiveConfig.from_env reads ARCHIVE_MESSAGES."""
    with patch.dict(os.environ, {"ARCHIVE_MESSAGES": "1"}):
        config = ArchiveConfig.from_env()
        assert config.enabled is True

    with patch.dict(os.environ, {"ARCHIVE_MESSAGES": "0"}):
        config = ArchiveConfig.from_env()
        assert config.enabled is False


def test_cog_config_from_env() -> None:
    """CogConfig.from_env creates all sub-configs."""
    reset_config()
    config = CogConfig.from_env()
    assert isinstance(config.llm, LLMConfig)
    assert isinstance(config.reaction, ReactionConfig)
    assert isinstance(config.archive, ArchiveConfig)


def test_get_config_singleton() -> None:
    """get_config returns the same instance on repeated calls."""
    reset_config()
    config1 = get_config()
    config2 = get_config()
    assert config1 is config2


def test_set_config_replaces_singleton() -> None:
    """set_config replaces the global configuration."""
    reset_config()
    custom_config = CogConfig(llm=LLMConfig(max_tokens=999))
    set_config(custom_config)
    assert get_config().llm.max_tokens == 999
    reset_config()


# --- PoolAwareCog Tests ---


class TestCog(PoolAwareCog):
    """Test cog for pool tests."""

    @require_pool
    async def method_requiring_pool(self) -> str:
        return "pool available"

    @log_errors("Test operation failed")
    async def method_with_error(self) -> None:
        raise ValueError("test error")

    @log_errors("Recoverable error", return_value="fallback")
    async def method_with_fallback(self) -> str:
        raise ValueError("recoverable")


@pytest.fixture
def mock_bot() -> MagicMock:
    """Create a mock bot instance."""
    return MagicMock()


@pytest.mark.asyncio
async def test_pool_aware_cog_init(mock_bot: MagicMock) -> None:
    """PoolAwareCog initializes with bot reference."""
    cog = TestCog(mock_bot)
    assert cog.bot is mock_bot
    assert cog.pool is None


@pytest.mark.asyncio
async def test_pool_aware_cog_load_success(mock_bot: MagicMock) -> None:
    """cog_load initializes pool when database is available."""
    cog = TestCog(mock_bot)
    mock_pool = AsyncMock()

    with patch("gentlebot.infra.cog_base.get_pool", return_value=mock_pool):
        await cog.cog_load()

    assert cog.pool is mock_pool


@pytest.mark.asyncio
async def test_pool_aware_cog_load_failure(mock_bot: MagicMock) -> None:
    """cog_load handles missing database gracefully."""
    cog = TestCog(mock_bot)

    with patch("gentlebot.infra.cog_base.get_pool", side_effect=RuntimeError("PG_DSN missing")):
        await cog.cog_load()

    assert cog.pool is None


@pytest.mark.asyncio
async def test_pool_aware_cog_unload(mock_bot: MagicMock) -> None:
    """cog_unload clears pool reference."""
    cog = TestCog(mock_bot)
    cog.pool = AsyncMock()

    await cog.cog_unload()

    assert cog.pool is None


@pytest.mark.asyncio
async def test_has_pool_property(mock_bot: MagicMock) -> None:
    """has_pool returns correct boolean."""
    cog = TestCog(mock_bot)
    assert cog.has_pool is False

    cog.pool = AsyncMock()
    assert cog.has_pool is True


@pytest.mark.asyncio
async def test_require_pool_skips_when_no_pool(mock_bot: MagicMock) -> None:
    """require_pool decorator returns None when pool is unavailable."""
    cog = TestCog(mock_bot)
    cog.pool = None

    result = await cog.method_requiring_pool()

    assert result is None


@pytest.mark.asyncio
async def test_require_pool_executes_with_pool(mock_bot: MagicMock) -> None:
    """require_pool decorator allows execution when pool is available."""
    cog = TestCog(mock_bot)
    cog.pool = AsyncMock()

    result = await cog.method_requiring_pool()

    assert result == "pool available"


@pytest.mark.asyncio
async def test_log_errors_logs_exception(mock_bot: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    """log_errors decorator logs exceptions."""
    cog = TestCog(mock_bot)

    with caplog.at_level(logging.ERROR):
        await cog.method_with_error()

    assert "Test operation failed" in caplog.text


@pytest.mark.asyncio
async def test_log_errors_returns_fallback(mock_bot: MagicMock) -> None:
    """log_errors decorator can return fallback value."""
    cog = TestCog(mock_bot)

    result = await cog.method_with_fallback()

    assert result == "fallback"
