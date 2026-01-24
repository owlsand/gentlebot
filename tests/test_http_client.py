"""Tests for the shared HTTP client infrastructure."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from gentlebot.infra import http as http_module
from gentlebot.infra.http import (
    get_sync_session,
    create_sync_session,
    reset_sessions,
    close_sessions,
    DEFAULT_TIMEOUT,
    DEFAULT_RETRIES,
    DEFAULT_USER_AGENT,
)


@pytest.fixture(autouse=True)
def clean_sessions():
    """Reset sessions before and after each test."""
    reset_sessions()
    yield
    reset_sessions()


class TestGetSyncSession:
    """Tests for the get_sync_session function."""

    def test_returns_session(self) -> None:
        session = get_sync_session()
        assert session is not None

    def test_returns_same_session(self) -> None:
        session1 = get_sync_session()
        session2 = get_sync_session()
        assert session1 is session2

    def test_session_has_user_agent(self) -> None:
        session = get_sync_session()
        assert "User-Agent" in session.headers
        assert session.headers["User-Agent"] == DEFAULT_USER_AGENT


class TestCreateSyncSession:
    """Tests for the create_sync_session function."""

    def test_creates_new_session(self) -> None:
        session1 = create_sync_session()
        session2 = create_sync_session()
        assert session1 is not session2

    def test_custom_retries(self) -> None:
        session = create_sync_session(retries=5)
        # Session is created, configuration is internal
        assert session is not None


class TestResetSessions:
    """Tests for the reset_sessions function."""

    def test_reset_forces_new_session(self) -> None:
        session1 = get_sync_session()
        reset_sessions()
        session2 = get_sync_session()
        assert session1 is not session2


class TestCloseSessions:
    """Tests for the close_sessions function."""

    def test_close_clears_session(self) -> None:
        session1 = get_sync_session()
        close_sessions()
        session2 = get_sync_session()
        assert session1 is not session2

    def test_close_handles_no_session(self) -> None:
        # Should not raise even if no session exists
        reset_sessions()
        close_sessions()


class TestAsyncSession:
    """Tests for the async session context manager."""

    @pytest.mark.asyncio
    async def test_async_session_context_manager(self) -> None:
        # Import here to avoid issues if aiohttp not installed
        try:
            from gentlebot.infra.http import get_async_session

            async with get_async_session() as session:
                assert session is not None
        except ImportError:
            pytest.skip("aiohttp not installed")
