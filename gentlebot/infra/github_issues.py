"""GitHub issue creation for automatic error reporting.

This module provides the core logic for creating GitHub issues from log records,
including fingerprint computation for deduplication and rate limiting.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import aiohttp

log = logging.getLogger(f"gentlebot.{__name__}")

# Match the pattern used by other infra modules for file-based logging
_file_log = logging.getLogger("gentlebot.github_issues.internal")


@dataclass
class GitHubIssueConfig:
    """Configuration for GitHub issue creation.

    Attributes:
        enabled: Whether issue creation is enabled.
        token: GitHub personal access token with repo scope.
        repo: Target repository in owner/repo format.
        rate_limit: Maximum issues per hour.
        dedup_hours: Hours to suppress duplicate issues.
        labels: Labels to apply to created issues.
    """

    enabled: bool = False
    token: str = ""
    repo: str = ""
    rate_limit: int = 10
    dedup_hours: int = 24
    labels: list[str] = field(default_factory=lambda: ["bug", "auto-generated"])


def get_github_issue_config() -> GitHubIssueConfig:
    """Load GitHub issue configuration from environment variables.

    Returns:
        GitHubIssueConfig populated from environment.
    """
    labels_str = os.getenv("GITHUB_ISSUE_LABELS", "bug,auto-generated")
    labels = [label.strip() for label in labels_str.split(",") if label.strip()]

    def _int_env(var: str, default: int) -> int:
        """Return int value from env, tolerating inline comments."""
        raw = os.getenv(var)
        if raw is None:
            return default
        value = raw.split("#", 1)[0].strip()
        if not value:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            log.warning("Invalid integer for %s: %s; using %s", var, raw, default)
            return default

    return GitHubIssueConfig(
        enabled=os.getenv("GITHUB_ISSUES_ENABLED", "").lower() in ("true", "1", "yes"),
        token=os.getenv("GITHUB_TOKEN", ""),
        repo=os.getenv("GITHUB_REPO", ""),
        rate_limit=_int_env("GITHUB_ISSUE_RATE_LIMIT", 10),
        dedup_hours=_int_env("GITHUB_ISSUE_DEDUP_HOURS", 24),
        labels=labels,
    )


def _normalize_message(message: str) -> str:
    """Normalize a log message for fingerprinting.

    Replaces numbers and quoted strings with placeholders to group
    similar errors together.

    Args:
        message: The raw log message.

    Returns:
        Normalized message for fingerprinting.
    """
    # Replace numbers with N
    normalized = re.sub(r"\b\d+\b", "N", message)
    # Replace quoted strings with X
    normalized = re.sub(r'"[^"]*"', '"X"', normalized)
    normalized = re.sub(r"'[^']*'", "'X'", normalized)
    # Collapse variable usernames after "role N to/from" for roles_cog dedup
    normalized = re.sub(
        r"(role N (?:to|from)) .+?(?=\. Ensure)", r"\1 <name>", normalized
    )
    return normalized


def _extract_stack_frames(exc_info: tuple | None) -> list[str]:
    """Extract the last 3 stack frames from exception info.

    Args:
        exc_info: Exception info tuple (type, value, traceback).

    Returns:
        List of "file:function:line" strings for the last 3 frames.
    """
    if not exc_info or not exc_info[2]:
        return []

    frames = []
    tb = exc_info[2]
    while tb is not None:
        frame = tb.tb_frame
        frames.append(f"{frame.f_code.co_filename}:{frame.f_code.co_name}:{tb.tb_lineno}")
        tb = tb.tb_next

    # Return last 3 frames (most relevant)
    return frames[-3:] if len(frames) >= 3 else frames


def compute_error_fingerprint(record: logging.LogRecord) -> str:
    """Compute a fingerprint for deduplication.

    The fingerprint is a hash of:
    - Exception type (if present)
    - Last 3 stack frames
    - Logger name
    - Normalized message

    Args:
        record: The log record.

    Returns:
        8-character hex fingerprint.
    """
    components = []

    # Exception type
    if record.exc_info and record.exc_info[0]:
        components.append(record.exc_info[0].__name__)

    # Stack frames
    frames = _extract_stack_frames(record.exc_info)
    components.extend(frames)

    # Logger name
    components.append(record.name)

    # Normalized message
    components.append(_normalize_message(record.getMessage()))

    # Hash all components
    fingerprint_str = "|".join(components)
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:8]


def format_issue_title(record: logging.LogRecord) -> str:
    """Format a GitHub issue title from a log record.

    Format: [ExceptionType] component: brief message

    Args:
        record: The log record.

    Returns:
        Issue title (max 100 characters).
    """
    # Extract component from logger name (e.g., "gentlebot.cogs.roles_cog" -> "roles_cog")
    parts = record.name.split(".")
    component = parts[-1] if len(parts) > 1 else parts[0]

    # Exception type
    exc_type = ""
    if record.exc_info and record.exc_info[0]:
        exc_type = f"[{record.exc_info[0].__name__}] "

    # Brief message
    message = record.getMessage()
    if len(message) > 60:
        message = message[:57] + "..."

    title = f"{exc_type}{component}: {message}"
    return title[:100] if len(title) > 100 else title


def format_issue_body(
    record: logging.LogRecord,
    fingerprint: str,
    env: str = "PROD",
) -> str:
    """Format a GitHub issue body from a log record.

    Args:
        record: The log record.
        fingerprint: The computed fingerprint.
        env: Environment name (PROD/TEST).

    Returns:
        Markdown-formatted issue body.
    """
    timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()

    # Build stack trace section
    stack_trace = ""
    if record.exc_info and record.exc_info[0]:
        stack_trace = "".join(traceback.format_exception(*record.exc_info))

    # Build the body
    body_parts = [
        "## Error Details",
        f"**Logger:** `{record.name}`",
        f"**Level:** {record.levelname}",
        f"**Timestamp:** {timestamp}",
        f"**Environment:** {env}",
        f"**Fingerprint:** `{fingerprint}`",
        "",
        "## Message",
        "```",
        record.getMessage(),
        "```",
    ]

    if stack_trace:
        body_parts.extend([
            "",
            "## Stack Trace",
            "```python",
            stack_trace.strip(),
            "```",
        ])

    body_parts.extend([
        "",
        "---",
        "*This issue was automatically created by Gentlebot error monitoring.*",
    ])

    return "\n".join(body_parts)


class IssueRateLimiter:
    """Sliding window rate limiter for issue creation.

    Uses an in-memory deque of timestamps to track issue creation.
    """

    def __init__(self, max_per_hour: int = 10) -> None:
        """Initialize the rate limiter.

        Args:
            max_per_hour: Maximum issues allowed per hour.
        """
        self.max_per_hour = max_per_hour
        self._timestamps: deque[datetime] = deque()

    def _prune_old(self) -> None:
        """Remove timestamps older than 1 hour."""
        now = datetime.now(timezone.utc)
        one_hour_ago = now.replace(hour=now.hour - 1 if now.hour > 0 else 23)
        # For hour=0, we need to handle the day boundary
        if now.hour == 0:
            one_hour_ago = now.replace(
                day=now.day - 1 if now.day > 1 else 1,
                hour=23,
            )

        # Simple approach: remove entries older than 3600 seconds
        cutoff = datetime.now(timezone.utc)
        while self._timestamps and (cutoff - self._timestamps[0]).total_seconds() > 3600:
            self._timestamps.popleft()

    def can_create_issue(self) -> bool:
        """Check if an issue can be created without exceeding the rate limit.

        Returns:
            True if creation is allowed, False otherwise.
        """
        self._prune_old()
        return len(self._timestamps) < self.max_per_hour

    def record_issue(self) -> None:
        """Record that an issue was created."""
        self._timestamps.append(datetime.now(timezone.utc))

    def remaining(self) -> int:
        """Return the number of issues that can still be created this hour."""
        self._prune_old()
        return max(0, self.max_per_hour - len(self._timestamps))


async def create_github_issue(
    config: GitHubIssueConfig,
    title: str,
    body: str,
) -> dict[str, Any] | None:
    """Create a GitHub issue via the REST API.

    Args:
        config: GitHub issue configuration.
        title: Issue title.
        body: Issue body (markdown).

    Returns:
        The created issue data, or None if creation failed.
    """
    if not config.token or not config.repo:
        _file_log.warning("GitHub issue creation skipped: missing token or repo")
        return None

    url = f"https://api.github.com/repos/{config.repo}/issues"
    headers = {
        "Authorization": f"token {config.token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Gentlebot-Error-Monitor",
    }
    payload = {
        "title": title,
        "body": body,
        "labels": config.labels,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 201:
                    data = await resp.json()
                    _file_log.info("Created GitHub issue: %s", data.get("html_url"))
                    return data
                else:
                    error_text = await resp.text()
                    _file_log.error(
                        "Failed to create GitHub issue: %s %s",
                        resp.status,
                        error_text[:200],
                    )
                    return None
    except aiohttp.ClientError as exc:
        _file_log.error("GitHub API request failed: %s", exc)
        return None
    except Exception as exc:
        _file_log.error("Unexpected error creating GitHub issue: %s", exc)
        return None
