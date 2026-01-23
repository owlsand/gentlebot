"""
Custom exception hierarchy for Gentlebot.

This module defines all custom exceptions used throughout the application,
providing a clear hierarchy for error handling.
"""
from __future__ import annotations


class GentlebotError(Exception):
    """
    Base exception for all Gentlebot errors.

    All custom exceptions should inherit from this class.
    This allows catching all Gentlebot-specific errors with a single except clause.
    """

    def __init__(self, message: str, user_message: str | None = None):
        """
        Initialize a Gentlebot error.

        Args:
            message: Technical error message for logging
            user_message: User-friendly message to display (optional)
        """
        super().__init__(message)
        self.message = message
        self.user_message = user_message or message

    def __str__(self) -> str:
        return self.message


class ConfigurationError(GentlebotError):
    """
    Raised when there's a configuration problem.

    Examples:
        - Missing required environment variables
        - Invalid configuration values
        - Misconfigured features
    """

    def __init__(self, message: str, config_key: str | None = None):
        """
        Initialize a configuration error.

        Args:
            message: Error description
            config_key: The configuration key that caused the error
        """
        self.config_key = config_key
        user_msg = "There's a configuration issue. Please contact the bot administrator."
        super().__init__(message, user_msg)


class APIError(GentlebotError):
    """
    Raised when an external API call fails.

    Examples:
        - HTTP errors from external services
        - API rate limits
        - Invalid API responses
    """

    def __init__(
        self,
        message: str,
        api_name: str | None = None,
        status_code: int | None = None,
        user_message: str | None = None,
    ):
        """
        Initialize an API error.

        Args:
            message: Error description
            api_name: Name of the API that failed
            status_code: HTTP status code if applicable
            user_message: User-friendly error message
        """
        self.api_name = api_name
        self.status_code = status_code
        default_user_msg = f"Unable to connect to {api_name or 'external service'}. Please try again later."
        super().__init__(message, user_message or default_user_msg)


class RateLimitError(APIError):
    """
    Raised when a rate limit is exceeded.

    This is a specific type of API error for rate limiting.
    """

    def __init__(self, message: str, retry_after: int | None = None):
        """
        Initialize a rate limit error.

        Args:
            message: Error description
            retry_after: Seconds until retry is allowed
        """
        self.retry_after = retry_after
        user_msg = "I'm being rate limited. Please try again in a moment."
        super().__init__(message, user_message=user_msg)


class ValidationError(GentlebotError):
    """
    Raised when input validation fails.

    Examples:
        - Invalid user input
        - Malformed data
        - Out-of-range values
    """

    def __init__(self, message: str, field: str | None = None):
        """
        Initialize a validation error.

        Args:
            message: Error description
            field: The field that failed validation
        """
        self.field = field
        super().__init__(message, message)  # Validation errors can be shown to users


class DatabaseError(GentlebotError):
    """
    Raised when a database operation fails.

    Examples:
        - Connection failures
        - Query errors
        - Constraint violations
    """

    def __init__(self, message: str, operation: str | None = None):
        """
        Initialize a database error.

        Args:
            message: Error description
            operation: The operation that failed (e.g., "insert", "update")
        """
        self.operation = operation
        user_msg = "A database error occurred. The operation could not be completed."
        super().__init__(message, user_msg)


class DiscordOperationError(GentlebotError):
    """
    Raised when a Discord API operation fails.

    Examples:
        - Permission errors
        - Missing channels/roles
        - Message send failures
    """

    def __init__(self, message: str, operation: str | None = None):
        """
        Initialize a Discord operation error.

        Args:
            message: Error description
            operation: The Discord operation that failed
        """
        self.operation = operation
        super().__init__(message, "I couldn't complete that Discord operation. Check my permissions.")
