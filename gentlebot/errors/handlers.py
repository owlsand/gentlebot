"""
Centralized error handlers for Discord bot commands and events.

This module provides error handling infrastructure that can be registered
with the Discord bot to provide consistent error responses and logging.
"""
from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from .exceptions import (
    GentlebotError,
    ConfigurationError,
    APIError,
    ValidationError,
    DatabaseError,
    DiscordOperationError,
    RateLimitError,
)

if TYPE_CHECKING:
    from discord import Interaction

log = logging.getLogger(__name__)


async def handle_application_command_error(
    interaction: Interaction,
    error: Exception,
) -> None:
    """
    Handle errors from application commands (slash commands).

    This handler provides user-friendly error messages while logging
    the full error details for debugging.

    Args:
        interaction: The Discord interaction that caused the error
        error: The exception that was raised
    """
    # Get the original error if it's wrapped in a CommandInvokeError
    original_error = error
    if isinstance(error, commands.CommandInvokeError):
        original_error = error.original

    # Log the error with context
    user_info = f"{interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id})"
    command_info = interaction.command.name if interaction.command else "unknown"
    log.error(
        "Error in command '%s' by user %s: %s",
        command_info,
        user_info,
        original_error,
        exc_info=original_error,
    )

    # Determine user-facing message based on error type
    user_message = _get_user_message(original_error)

    # Send error response to user
    try:
        if interaction.response.is_done():
            await interaction.followup.send(user_message, ephemeral=True)
        else:
            await interaction.response.send_message(user_message, ephemeral=True)
    except discord.HTTPException:
        log.exception("Failed to send error message to user")


async def handle_command_error(ctx: commands.Context, error: Exception) -> None:
    """
    Handle errors from text-based commands (prefix commands).

    Args:
        ctx: The command context
        error: The exception that was raised
    """
    # Get the original error if it's wrapped
    original_error = error
    if isinstance(error, commands.CommandInvokeError):
        original_error = error.original

    # Log the error with context
    user_info = f"{ctx.author.name}#{ctx.author.discriminator} ({ctx.author.id})"
    command_info = ctx.command.name if ctx.command else "unknown"
    log.error(
        "Error in command '%s' by user %s: %s",
        command_info,
        user_info,
        original_error,
        exc_info=original_error,
    )

    # Determine user-facing message
    user_message = _get_user_message(original_error)

    # Send error response
    try:
        await ctx.send(user_message, ephemeral=True)
    except discord.HTTPException:
        log.exception("Failed to send error message to user")


def _get_user_message(error: Exception) -> str:
    """
    Get a user-friendly error message based on the error type.

    Args:
        error: The exception

    Returns:
        User-friendly error message
    """
    # Handle Gentlebot custom exceptions
    if isinstance(error, GentlebotError):
        return f"❌ {error.user_message}"

    # Handle Discord.py exceptions
    if isinstance(error, commands.MissingPermissions):
        perms = ", ".join(error.missing_permissions)
        return f"❌ You don't have the required permissions: {perms}"

    if isinstance(error, commands.BotMissingPermissions):
        perms = ", ".join(error.missing_permissions)
        return f"❌ I don't have the required permissions: {perms}"

    if isinstance(error, commands.MissingRequiredArgument):
        return f"❌ Missing required argument: {error.param.name}"

    if isinstance(error, commands.BadArgument):
        return f"❌ Invalid argument: {error}"

    if isinstance(error, commands.CommandNotFound):
        return "❌ Command not found."

    if isinstance(error, commands.CommandOnCooldown):
        return f"❌ This command is on cooldown. Try again in {error.retry_after:.1f}s."

    if isinstance(error, discord.Forbidden):
        return "❌ I don't have permission to do that."

    if isinstance(error, discord.NotFound):
        return "❌ The requested resource was not found."

    if isinstance(error, discord.HTTPException):
        return "❌ A Discord API error occurred. Please try again."

    # Generic error message for unknown errors
    return "❌ An unexpected error occurred. The error has been logged."


async def on_error_event(event_name: str, *args, **kwargs) -> None:
    """
    Global error handler for Discord events.

    This catches errors that occur in event handlers.

    Args:
        event_name: Name of the event that caused the error
        *args: Event arguments
        **kwargs: Event keyword arguments
    """
    log.error(
        "Error in event '%s': %s",
        event_name,
        traceback.format_exc(),
    )


def setup_error_handlers(bot: commands.Bot) -> None:
    """
    Register error handlers with the Discord bot.

    This should be called during bot initialization.

    Args:
        bot: The Discord bot instance
    """

    @bot.event
    async def on_command_error(ctx: commands.Context, error: Exception) -> None:
        """Handle errors from prefix commands."""
        await handle_command_error(ctx, error)

    @bot.tree.error
    async def on_app_command_error(
        interaction: Interaction, error: Exception
    ) -> None:
        """Handle errors from application commands."""
        await handle_application_command_error(interaction, error)

    @bot.event
    async def on_error(event: str, *args, **kwargs) -> None:
        """Handle errors from events."""
        await on_error_event(event, *args, **kwargs)

    log.info("Error handlers registered successfully")


def handle_sync_error(error: Exception, context: str = "") -> str:
    """
    Handle errors in synchronous code paths.

    This is useful for error handling in non-async contexts.

    Args:
        error: The exception
        context: Additional context about where the error occurred

    Returns:
        User-friendly error message
    """
    if context:
        log.error("Error in %s: %s", context, error, exc_info=error)
    else:
        log.error("Error: %s", error, exc_info=error)

    return _get_user_message(error)
