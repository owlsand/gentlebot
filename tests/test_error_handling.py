"""Tests for the centralized error handling system."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from gentlebot.errors import (
    GentlebotError,
    ConfigurationError,
    APIError,
    ValidationError,
    DatabaseError,
    DiscordOperationError,
    RateLimitError,
)
from gentlebot.errors.handlers import _get_user_message, handle_sync_error


def test_gentlebot_error_base():
    """Test the base GentlebotError exception."""
    error = GentlebotError("Technical message", "User-friendly message")
    assert str(error) == "Technical message"
    assert error.message == "Technical message"
    assert error.user_message == "User-friendly message"

    # Test without user message
    error = GentlebotError("Technical message")
    assert error.user_message == "Technical message"


def test_configuration_error():
    """Test ConfigurationError exception."""
    error = ConfigurationError("Missing API key", config_key="GEMINI_API_KEY")
    assert error.config_key == "GEMINI_API_KEY"
    assert "configuration issue" in error.user_message.lower()


def test_api_error():
    """Test APIError exception."""
    error = APIError(
        "API request failed",
        api_name="Gemini",
        status_code=500,
        user_message="Custom user message",
    )
    assert error.api_name == "Gemini"
    assert error.status_code == 500
    assert error.user_message == "Custom user message"

    # Test with default user message
    error = APIError("API failed", api_name="TestAPI")
    assert "TestAPI" in error.user_message


def test_rate_limit_error():
    """Test RateLimitError exception."""
    error = RateLimitError("Rate limit exceeded", retry_after=60)
    assert error.retry_after == 60
    assert "rate limited" in error.user_message.lower()
    assert isinstance(error, APIError)  # Should be subclass of APIError


def test_validation_error():
    """Test ValidationError exception."""
    error = ValidationError("Invalid email format", field="email")
    assert error.field == "email"
    # Validation errors should show user the message
    assert error.user_message == "Invalid email format"


def test_database_error():
    """Test DatabaseError exception."""
    error = DatabaseError("Connection failed", operation="insert")
    assert error.operation == "insert"
    assert "database error" in error.user_message.lower()


def test_discord_operation_error():
    """Test DiscordOperationError exception."""
    error = DiscordOperationError("Failed to send message", operation="send_message")
    assert error.operation == "send_message"
    assert "discord operation" in error.user_message.lower()


def test_get_user_message_with_gentlebot_errors():
    """Test _get_user_message with Gentlebot custom errors."""
    error = APIError("API failed", user_message="Custom message")
    msg = _get_user_message(error)
    assert "❌" in msg
    assert "Custom message" in msg


def test_get_user_message_with_discord_errors():
    """Test _get_user_message with Discord.py errors."""
    from discord.ext import commands

    # Test MissingPermissions
    error = commands.MissingPermissions(["manage_messages", "kick_members"])
    msg = _get_user_message(error)
    assert "❌" in msg
    assert "permissions" in msg.lower()
    assert "manage_messages" in msg

    # Test CommandOnCooldown
    error = commands.CommandOnCooldown(None, 30.5)
    msg = _get_user_message(error)
    assert "❌" in msg
    assert "cooldown" in msg.lower()
    assert "30.5" in msg


def test_handle_sync_error():
    """Test handle_sync_error for synchronous error handling."""
    error = ValidationError("Test validation error")

    with patch("gentlebot.errors.handlers.log") as mock_log:
        msg = handle_sync_error(error, context="test_function")
        assert "❌" in msg
        assert "Test validation error" in msg
        mock_log.error.assert_called_once()


@pytest.mark.asyncio
async def test_handle_application_command_error():
    """Test error handling for application commands."""
    from gentlebot.errors.handlers import handle_application_command_error

    # Create mock interaction
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.name = "TestUser"
    interaction.user.discriminator = "1234"
    interaction.user.id = 123456789
    interaction.command = MagicMock()
    interaction.command.name = "test_command"
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.send_message = AsyncMock()

    # Test with custom error
    error = ValidationError("Invalid input")
    with patch("gentlebot.errors.handlers.log") as mock_log:
        await handle_application_command_error(interaction, error)
        mock_log.error.assert_called_once()
        interaction.response.send_message.assert_called_once()
        call_args = interaction.response.send_message.call_args
        assert "❌" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True


@pytest.mark.asyncio
async def test_handle_command_error():
    """Test error handling for text commands."""
    from gentlebot.errors.handlers import handle_command_error

    # Create mock context
    ctx = MagicMock()
    ctx.author = MagicMock()
    ctx.author.name = "TestUser"
    ctx.author.discriminator = "1234"
    ctx.author.id = 123456789
    ctx.command = MagicMock()
    ctx.command.name = "test_command"
    ctx.send = AsyncMock()

    # Test with custom error
    error = DatabaseError("Connection failed")
    with patch("gentlebot.errors.handlers.log") as mock_log:
        await handle_command_error(ctx, error)
        mock_log.error.assert_called_once()
        ctx.send.assert_called_once()
        call_args = ctx.send.call_args
        assert "❌" in call_args[0][0]


def test_error_hierarchy():
    """Test that custom exceptions form proper hierarchy."""
    api_error = APIError("Test")
    rate_limit = RateLimitError("Test")

    assert isinstance(api_error, GentlebotError)
    assert isinstance(rate_limit, APIError)
    assert isinstance(rate_limit, GentlebotError)
    assert isinstance(ConfigurationError("Test"), GentlebotError)
    assert isinstance(ValidationError("Test"), GentlebotError)
    assert isinstance(DatabaseError("Test"), GentlebotError)
    assert isinstance(DiscordOperationError("Test"), GentlebotError)
