"""Centralized error handling for Gentlebot."""
from .exceptions import (
    GentlebotError,
    ConfigurationError,
    APIError,
    ValidationError,
    DatabaseError,
    DiscordOperationError,
    RateLimitError,
)
from .handlers import setup_error_handlers

__all__ = [
    "GentlebotError",
    "ConfigurationError",
    "APIError",
    "ValidationError",
    "DatabaseError",
    "DiscordOperationError",
    "RateLimitError",
    "setup_error_handlers",
]
