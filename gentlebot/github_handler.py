"""Logging handler for automatic GitHub issue creation.

This module provides a custom Python logging.Handler that creates GitHub issues
for ERROR and CRITICAL level log messages, following the same async pattern
as PostgresHandler.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from .infra.github_issues import (
    GitHubIssueConfig,
    IssueRateLimiter,
    compute_error_fingerprint,
    create_github_issue,
    format_issue_body,
    format_issue_title,
)
from .infra.state_cache import get_state_cache

# Use a separate logger that won't trigger this handler (prevents recursion)
_internal_log = logging.getLogger("gentlebot.github_handler.internal")


class GitHubIssueHandler(logging.Handler):
    """Asynchronously create GitHub issues for ERROR and CRITICAL logs.

    This handler captures ERROR and CRITICAL level log records and creates
    GitHub issues for them, with deduplication and rate limiting.

    Example::

        config = get_github_issue_config()
        handler = GitHubIssueHandler(config)
        await handler.connect()
        root_logger.addHandler(handler)
    """

    def __init__(self, config: GitHubIssueConfig) -> None:
        """Initialize the handler.

        Args:
            config: GitHub issue configuration.
        """
        super().__init__()
        self.config = config
        self.loop: asyncio.AbstractEventLoop | None = None
        self._rate_limiter = IssueRateLimiter(config.rate_limit)
        self._state_cache = get_state_cache()
        self._env = os.getenv("env", "PROD").upper()

        # Only capture ERROR and CRITICAL
        self.setLevel(logging.ERROR)

    async def connect(self) -> None:
        """Initialize the handler with the current event loop."""
        self.loop = asyncio.get_running_loop()
        _internal_log.info(
            "GitHubIssueHandler initialized (enabled=%s, repo=%s)",
            self.config.enabled,
            self.config.repo,
        )

    def _is_internal_log(self, record: logging.LogRecord) -> bool:
        """Check if this is an internal log (to prevent recursion).

        Args:
            record: The log record.

        Returns:
            True if this is an internal log that should be skipped.
        """
        return record.name.startswith("gentlebot.github_handler") or record.name.startswith(
            "gentlebot.infra.github_issues"
        )

    def _get_dedup_key(self, fingerprint: str) -> str:
        """Get the state cache key for deduplication.

        Args:
            fingerprint: The error fingerprint.

        Returns:
            Cache key for deduplication lookup.
        """
        return f"github_issue:{fingerprint}"

    def _is_duplicate(self, fingerprint: str) -> tuple[bool, str | None]:
        """Check if this error has been reported recently.

        Args:
            fingerprint: The error fingerprint.

        Returns:
            Tuple of (is_duplicate, existing_issue_url).
        """
        key = self._get_dedup_key(fingerprint)
        cached = self._state_cache.get(key)
        if cached and isinstance(cached, dict):
            return True, cached.get("issue_url")
        return False, None

    def _record_issue(self, fingerprint: str, issue_url: str) -> None:
        """Record that an issue was created for this fingerprint.

        Args:
            fingerprint: The error fingerprint.
            issue_url: The URL of the created issue.
        """
        key = self._get_dedup_key(fingerprint)
        self._state_cache.set(
            key,
            {
                "issue_url": issue_url,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            ttl_hours=self.config.dedup_hours,
        )

    async def _emit_async(self, record: logging.LogRecord) -> None:
        """Async implementation of issue creation.

        Args:
            record: The log record.
        """
        try:
            # Compute fingerprint
            fingerprint = compute_error_fingerprint(record)

            # Check for duplicate
            is_dup, existing_url = self._is_duplicate(fingerprint)
            if is_dup:
                _internal_log.debug(
                    "Skipping duplicate issue (fingerprint=%s, existing=%s)",
                    fingerprint,
                    existing_url,
                )
                return

            # Check rate limit
            if not self._rate_limiter.can_create_issue():
                _internal_log.warning(
                    "Rate limit exceeded, skipping issue creation (remaining=%d)",
                    self._rate_limiter.remaining(),
                )
                return

            # Format issue
            title = format_issue_title(record)
            body = format_issue_body(record, fingerprint, self._env)

            # Create issue
            result = await create_github_issue(self.config, title, body)
            if result:
                issue_url = result.get("html_url", "")
                self._rate_limiter.record_issue()
                self._record_issue(fingerprint, issue_url)
                _internal_log.info(
                    "Created GitHub issue for %s: %s",
                    record.name,
                    issue_url,
                )

        except Exception as exc:
            # Never let handler errors propagate
            _internal_log.error("Error in GitHubIssueHandler: %s", exc)

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record by creating a GitHub issue.

        Args:
            record: The log record.
        """
        # Skip if not enabled or missing config
        if not self.config.enabled or not self.config.token or not self.config.repo:
            return

        # Skip if no loop
        if not self.loop:
            return

        # Skip internal logs to prevent recursion
        if self._is_internal_log(record):
            return

        # Schedule async emission
        coro = self._emit_async(record)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Not in async context, use threadsafe scheduling
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        else:
            if loop is self.loop:
                loop.create_task(coro)
            else:
                asyncio.run_coroutine_threadsafe(coro, self.loop)

    def close(self) -> None:
        """Close the handler."""
        self.loop = None
        super().close()
