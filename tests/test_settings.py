"""Tests for the centralized settings module."""
import os
import pytest


def test_settings_imports():
    """Test that settings can be imported successfully."""
    from gentlebot.config import settings

    assert settings is not None
    assert hasattr(settings, "env")
    assert hasattr(settings, "discord")
    assert hasattr(settings, "database")
    assert hasattr(settings, "api_keys")
    assert hasattr(settings, "features")


def test_settings_environment_detection():
    """Test that environment is properly detected."""
    from gentlebot.config.settings import Settings

    # Save original env
    original_env = os.environ.get("env")

    try:
        # Test PROD environment
        os.environ["env"] = "PROD"
        settings = Settings()
        assert settings.env == "PROD"
        assert settings.is_prod is True
        assert settings.is_test is False

        # Test TEST environment
        os.environ["env"] = "TEST"
        settings = Settings()
        assert settings.env == "TEST"
        assert settings.is_test is True
        assert settings.is_prod is False
    finally:
        # Restore original env
        if original_env:
            os.environ["env"] = original_env
        elif "env" in os.environ:
            del os.environ["env"]


def test_discord_config_validation():
    """Test that Discord configuration validates required fields."""
    from gentlebot.config.settings import DiscordConfig

    # Should require token
    with pytest.raises(ValueError, match="DISCORD_TOKEN is required"):
        DiscordConfig(
            token="",
            guild_id=12345,
            finance_channel_id=1,
            market_channel_id=1,
            f1_channel_id=1,
            sports_channel_id=1,
            fantasy_channel_id=1,
            daily_ping_channel=1,
            money_talk_channel=1,
        )

    # Should require guild_id
    with pytest.raises(ValueError, match="Guild ID is required"):
        DiscordConfig(
            token="test-token",
            guild_id=0,
            finance_channel_id=1,
            market_channel_id=1,
            f1_channel_id=1,
            sports_channel_id=1,
            fantasy_channel_id=1,
            daily_ping_channel=1,
            money_talk_channel=1,
        )


def test_auto_role_ids_property():
    """Test that auto_role_ids property filters out zero values."""
    from gentlebot.config import settings

    # Should not include 0 values
    assert 0 not in settings.auto_role_ids
    # Should be a set
    assert isinstance(settings.auto_role_ids, set)


def test_role_descriptions_property():
    """Test that role descriptions are provided."""
    from gentlebot.config import settings

    role_descriptions = settings.role_descriptions
    assert isinstance(role_descriptions, dict)
    # Should have descriptions for non-zero roles
    for role_id in settings.auto_role_ids:
        if role_id > 0:
            assert role_id in role_descriptions


def test_backward_compatibility():
    """Test that old bot_config imports still work."""
    from gentlebot import bot_config

    # Check that all expected attributes exist
    assert hasattr(bot_config, "TOKEN")
    assert hasattr(bot_config, "GUILD_ID")
    assert hasattr(bot_config, "env")
    assert hasattr(bot_config, "IS_TEST")
    assert hasattr(bot_config, "AUTO_ROLE_IDS")
    assert hasattr(bot_config, "ROLE_DESCRIPTIONS")
    assert hasattr(bot_config, "TIERED_BADGES")


def test_database_config():
    """Test database configuration loading."""
    from gentlebot.config.settings import DatabaseConfig

    # Save original env vars
    original_dsn = os.environ.get("PG_DSN")
    original_db_url = os.environ.get("DATABASE_URL")

    try:
        # Test with PG_DSN
        os.environ["PG_DSN"] = "postgresql+asyncpg://user:pass@host:5432/db"
        if "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]

        config = DatabaseConfig()
        assert config.dsn == "postgresql+asyncpg://user:pass@host:5432/db"

        # Test with DATABASE_URL
        del os.environ["PG_DSN"]
        os.environ["DATABASE_URL"] = "postgresql://user:pass@host:5432/db"

        config = DatabaseConfig()
        assert config.dsn == "postgresql://user:pass@host:5432/db"

    finally:
        # Restore original env vars
        if original_dsn:
            os.environ["PG_DSN"] = original_dsn
        elif "PG_DSN" in os.environ:
            del os.environ["PG_DSN"]

        if original_db_url:
            os.environ["DATABASE_URL"] = original_db_url
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]


def test_features_config():
    """Test feature flags configuration."""
    from gentlebot.config import settings

    assert hasattr(settings.features, "inactive_days")
    assert isinstance(settings.features.inactive_days, int)
    assert hasattr(settings.features, "daily_prompt_enabled")
    assert isinstance(settings.features.daily_prompt_enabled, bool)
