"""Tests for GitHub issue creation functionality."""
import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gentlebot.infra.github_issues import (
    GitHubIssueConfig,
    IssueRateLimiter,
    compute_error_fingerprint,
    create_github_issue,
    format_issue_body,
    format_issue_title,
    get_github_issue_config,
    _normalize_message,
)
from gentlebot.github_handler import GitHubIssueHandler


# ─── Fingerprint Tests ─────────────────────────────────────────────────────


def test_fingerprint_consistency():
    """Same error should produce the same fingerprint."""
    record1 = logging.LogRecord(
        name="gentlebot.cogs.test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="Failed to process user %s",
        args=(12345,),
        exc_info=None,
    )
    record2 = logging.LogRecord(
        name="gentlebot.cogs.test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="Failed to process user %s",
        args=(67890,),  # Different user ID
        exc_info=None,
    )

    fp1 = compute_error_fingerprint(record1)
    fp2 = compute_error_fingerprint(record2)

    # Numbers are normalized, so fingerprints should match
    assert fp1 == fp2
    assert len(fp1) == 8  # 8 hex characters


def test_fingerprint_uniqueness():
    """Different errors should produce different fingerprints."""
    record1 = logging.LogRecord(
        name="gentlebot.cogs.roles",
        level=logging.ERROR,
        pathname="roles.py",
        lineno=10,
        msg="Role assignment failed",
        args=(),
        exc_info=None,
    )
    record2 = logging.LogRecord(
        name="gentlebot.cogs.streak",
        level=logging.ERROR,
        pathname="streak.py",
        lineno=20,
        msg="Streak update failed",
        args=(),
        exc_info=None,
    )

    fp1 = compute_error_fingerprint(record1)
    fp2 = compute_error_fingerprint(record2)

    assert fp1 != fp2


def test_fingerprint_with_exception():
    """Fingerprint should include exception type."""
    try:
        raise ValueError("test error")
    except ValueError:
        import sys

        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="gentlebot.cogs.test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="An error occurred",
        args=(),
        exc_info=exc_info,
    )

    fp = compute_error_fingerprint(record)
    assert len(fp) == 8


def test_normalize_message():
    """Message normalization should replace numbers and quoted strings."""
    msg1 = "Failed to process user 12345 in channel 67890"
    msg2 = 'Error: "some value" was invalid'
    msg3 = "User 'john' with ID 999 failed"

    norm1 = _normalize_message(msg1)
    norm2 = _normalize_message(msg2)
    norm3 = _normalize_message(msg3)

    assert norm1 == "Failed to process user N in channel N"
    assert norm2 == 'Error: "X" was invalid'
    assert norm3 == "User 'X' with ID N failed"


# ─── Rate Limiter Tests ────────────────────────────────────────────────────


def test_rate_limiter_allows_under_limit():
    """Rate limiter should allow issues under the limit."""
    limiter = IssueRateLimiter(max_per_hour=5)

    for _ in range(5):
        assert limiter.can_create_issue()
        limiter.record_issue()

    # 6th should be blocked
    assert not limiter.can_create_issue()


def test_rate_limiter_remaining():
    """Remaining count should be accurate."""
    limiter = IssueRateLimiter(max_per_hour=10)

    assert limiter.remaining() == 10

    limiter.record_issue()
    assert limiter.remaining() == 9

    for _ in range(5):
        limiter.record_issue()
    assert limiter.remaining() == 4


def test_rate_limiter_prunes_old():
    """Rate limiter should prune old entries."""
    limiter = IssueRateLimiter(max_per_hour=2)

    # Add an old timestamp
    old_time = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    limiter._timestamps.append(old_time)

    # Should be pruned when checking
    assert limiter.can_create_issue()


# ─── Formatting Tests ──────────────────────────────────────────────────────


def test_format_issue_title():
    """Issue title should be formatted correctly."""
    record = logging.LogRecord(
        name="gentlebot.cogs.roles_cog",
        level=logging.ERROR,
        pathname="roles_cog.py",
        lineno=45,
        msg="Failed to assign role to user",
        args=(),
        exc_info=None,
    )

    title = format_issue_title(record)

    assert "roles_cog" in title
    assert "Failed to assign role" in title


def test_format_issue_title_with_exception():
    """Issue title should include exception type."""
    try:
        raise ValueError("Invalid role ID")
    except ValueError:
        import sys

        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="gentlebot.cogs.roles_cog",
        level=logging.ERROR,
        pathname="roles_cog.py",
        lineno=45,
        msg="Role operation failed",
        args=(),
        exc_info=exc_info,
    )

    title = format_issue_title(record)

    assert "[ValueError]" in title


def test_format_issue_title_truncation():
    """Long titles should be truncated."""
    record = logging.LogRecord(
        name="gentlebot.cogs.test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="A" * 200,  # Very long message
        args=(),
        exc_info=None,
    )

    title = format_issue_title(record)

    assert len(title) <= 100


def test_format_issue_body():
    """Issue body should contain all required sections."""
    record = logging.LogRecord(
        name="gentlebot.cogs.roles_cog",
        level=logging.ERROR,
        pathname="roles_cog.py",
        lineno=45,
        msg="Failed to assign role",
        args=(),
        exc_info=None,
    )

    body = format_issue_body(record, "a1b2c3d4", "PROD")

    assert "## Error Details" in body
    assert "`gentlebot.cogs.roles_cog`" in body
    assert "ERROR" in body
    assert "PROD" in body
    assert "`a1b2c3d4`" in body
    assert "## Message" in body
    assert "Failed to assign role" in body
    assert "automatically created by Gentlebot" in body


def test_format_issue_body_with_stack_trace():
    """Issue body should include stack trace when present."""
    try:
        raise ValueError("test error")
    except ValueError:
        import sys

        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="gentlebot.cogs.test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="An error occurred",
        args=(),
        exc_info=exc_info,
    )

    body = format_issue_body(record, "abcd1234", "PROD")

    assert "## Stack Trace" in body
    assert "ValueError" in body
    assert "test error" in body


# ─── Config Tests ──────────────────────────────────────────────────────────


def test_get_github_issue_config_defaults(monkeypatch):
    """Default config should have sensible values."""
    monkeypatch.delenv("GITHUB_ISSUES_ENABLED", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)

    config = get_github_issue_config()

    assert config.enabled is False
    assert config.token == ""
    assert config.repo == ""
    assert config.rate_limit == 10
    assert config.dedup_hours == 24


def test_get_github_issue_config_from_env(monkeypatch):
    """Config should be loaded from environment."""
    monkeypatch.setenv("GITHUB_ISSUES_ENABLED", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    monkeypatch.setenv("GITHUB_ISSUE_RATE_LIMIT", "5")
    monkeypatch.setenv("GITHUB_ISSUE_DEDUP_HOURS", "48")
    monkeypatch.setenv("GITHUB_ISSUE_LABELS", "error,automated")

    config = get_github_issue_config()

    assert config.enabled is True
    assert config.token == "ghp_test123"
    assert config.repo == "owner/repo"
    assert config.rate_limit == 5
    assert config.dedup_hours == 48
    assert config.labels == ["error", "automated"]


# ─── Handler Tests ─────────────────────────────────────────────────────────


def test_handler_ignores_low_level_logs():
    """Handler should ignore INFO and DEBUG logs."""
    config = GitHubIssueConfig(enabled=True, token="test", repo="owner/repo")
    handler = GitHubIssueHandler(config)

    # Handler level is set to ERROR
    assert handler.level == logging.ERROR

    # INFO record should not pass the level check
    info_record = logging.LogRecord(
        name="gentlebot.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Info message",
        args=(),
        exc_info=None,
    )

    # The handler's level filter will prevent emit from processing INFO
    assert info_record.levelno < handler.level


def test_handler_skips_internal_logs():
    """Handler should skip its own internal logs to prevent recursion."""
    config = GitHubIssueConfig(enabled=True, token="test", repo="owner/repo")
    handler = GitHubIssueHandler(config)

    assert handler._is_internal_log(
        logging.LogRecord(
            name="gentlebot.github_handler.internal",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
    )

    assert handler._is_internal_log(
        logging.LogRecord(
            name="gentlebot.infra.github_issues.internal",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
    )

    assert not handler._is_internal_log(
        logging.LogRecord(
            name="gentlebot.cogs.roles_cog",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
    )


def test_handler_skips_when_disabled():
    """Handler should skip emit when disabled."""
    config = GitHubIssueConfig(enabled=False, token="test", repo="owner/repo")
    handler = GitHubIssueHandler(config)
    handler.loop = asyncio.new_event_loop()

    record = logging.LogRecord(
        name="gentlebot.test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="Error",
        args=(),
        exc_info=None,
    )

    # Should not raise, just return early
    handler.emit(record)
    handler.loop.close()


def test_handler_skips_without_loop():
    """Handler should skip emit when loop is not set."""
    config = GitHubIssueConfig(enabled=True, token="test", repo="owner/repo")
    handler = GitHubIssueHandler(config)
    # loop is None by default

    record = logging.LogRecord(
        name="gentlebot.test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="Error",
        args=(),
        exc_info=None,
    )

    # Should not raise, just return early
    handler.emit(record)


# ─── API Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_github_issue_success():
    """create_github_issue should handle successful API response."""
    config = GitHubIssueConfig(
        enabled=True,
        token="ghp_test",
        repo="owner/repo",
        labels=["bug"],
    )

    mock_response = AsyncMock()
    mock_response.status = 201
    mock_response.json = AsyncMock(
        return_value={"html_url": "https://github.com/owner/repo/issues/1"}
    )

    with patch("aiohttp.ClientSession") as mock_session:
        mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = (
            mock_response
        )
        result = await create_github_issue(config, "Test Issue", "Test body")

    assert result is not None
    assert result["html_url"] == "https://github.com/owner/repo/issues/1"


@pytest.mark.asyncio
async def test_create_github_issue_missing_config():
    """create_github_issue should return None when config is incomplete."""
    config = GitHubIssueConfig(enabled=True, token="", repo="owner/repo")

    result = await create_github_issue(config, "Test Issue", "Test body")

    assert result is None


@pytest.mark.asyncio
async def test_create_github_issue_api_error():
    """create_github_issue should handle API errors gracefully."""
    config = GitHubIssueConfig(
        enabled=True,
        token="ghp_test",
        repo="owner/repo",
    )

    mock_response = AsyncMock()
    mock_response.status = 401
    mock_response.text = AsyncMock(return_value="Bad credentials")

    with patch("aiohttp.ClientSession") as mock_session:
        mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = (
            mock_response
        )
        result = await create_github_issue(config, "Test Issue", "Test body")

    assert result is None


# ─── Deduplication Tests ───────────────────────────────────────────────────


def test_handler_deduplication():
    """Handler should detect duplicate errors."""
    config = GitHubIssueConfig(enabled=True, token="test", repo="owner/repo")
    handler = GitHubIssueHandler(config)

    # Manually set a cached fingerprint
    handler._state_cache.set(
        "github_issue:abcd1234",
        {"issue_url": "https://github.com/owner/repo/issues/1", "created_at": "2024-01-01T00:00:00Z"},
        ttl_hours=24,
    )

    is_dup, url = handler._is_duplicate("abcd1234")
    assert is_dup is True
    assert url == "https://github.com/owner/repo/issues/1"

    is_dup2, url2 = handler._is_duplicate("new_fingerprint")
    assert is_dup2 is False
    assert url2 is None

    # Clean up
    handler._state_cache.delete("github_issue:abcd1234")
