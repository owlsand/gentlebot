"""Integration tests for database operations."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncpg


@pytest.mark.asyncio
async def test_get_pool_creates_pool():
    """Test that get_pool creates a connection pool."""
    from gentlebot import db

    # Mock asyncpg.create_pool
    mock_pool = AsyncMock()
    mock_pool.is_closing = MagicMock(return_value=False)

    with patch.object(db.asyncpg, "create_pool", return_value=mock_pool) as mock_create:
        # Reset the global pool
        db._pool = None

        # Get pool
        pool = await db.get_pool()

        # Verify pool was created
        assert pool is mock_pool
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_get_pool_reuses_existing_pool():
    """Test that get_pool reuses an existing pool."""
    from gentlebot import db

    # Create a mock pool
    mock_pool = AsyncMock()
    mock_pool.is_closing = MagicMock(return_value=False)

    # Set the global pool
    db._pool = mock_pool

    with patch.object(db.asyncpg, "create_pool") as mock_create:
        # Get pool
        pool = await db.get_pool()

        # Should return existing pool without creating new one
        assert pool is mock_pool
        mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_get_pool_recreates_closed_pool():
    """Test that get_pool recreates a closed pool."""
    from gentlebot import db

    # Create a mock closed pool
    old_pool = AsyncMock()
    old_pool.is_closing = MagicMock(return_value=True)

    # Create a new mock pool
    new_pool = AsyncMock()
    new_pool.is_closing = MagicMock(return_value=False)

    # Set the global pool to the closed one
    db._pool = old_pool

    with patch.object(db.asyncpg, "create_pool", return_value=new_pool) as mock_create:
        # Get pool
        pool = await db.get_pool()

        # Should create a new pool
        assert pool is new_pool
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_close_pool():
    """Test that close_pool closes the pool."""
    from gentlebot import db

    # Create a mock pool
    mock_pool = AsyncMock()
    db._pool = mock_pool

    # Close pool
    await db.close_pool()

    # Verify pool was closed
    mock_pool.close.assert_called_once()
    assert db._pool is None


@pytest.mark.asyncio
async def test_get_pool_missing_dsn():
    """Test that get_pool raises error when DSN is missing."""
    from gentlebot import db
    import os

    # Save original env vars
    original_pg_dsn = os.environ.get("PG_DSN")
    original_db_url = os.environ.get("DATABASE_URL")
    original_pg_user = os.environ.get("PG_USER")

    try:
        # Clear all database env vars
        for key in ["PG_DSN", "DATABASE_URL", "PG_USER", "PG_PASSWORD", "PG_DB"]:
            if key in os.environ:
                del os.environ[key]

        # Reset pool
        db._pool = None

        # Should raise RuntimeError
        with pytest.raises(RuntimeError, match="PG_DSN is missing"):
            await db.get_pool()

    finally:
        # Restore env vars
        if original_pg_dsn:
            os.environ["PG_DSN"] = original_pg_dsn
        if original_db_url:
            os.environ["DATABASE_URL"] = original_db_url
        if original_pg_user:
            os.environ["PG_USER"] = original_pg_user


@pytest.mark.asyncio
async def test_pool_init_sets_search_path():
    """Test that pool initialization sets search_path."""
    from gentlebot import db
    import asyncpg

    # Mock connection
    mock_conn = AsyncMock()

    # Mock create_pool to capture init function
    captured_init = None

    async def mock_create_pool(url, init=None):
        nonlocal captured_init
        captured_init = init
        pool = AsyncMock()
        pool.is_closing = MagicMock(return_value=False)
        return pool

    # Reset pool
    db._pool = None

    with patch.object(asyncpg, "create_pool", side_effect=mock_create_pool):
        await db.get_pool()

        # Verify init function was provided
        assert captured_init is not None

        # Call init function with mock connection
        await captured_init(mock_conn)

        # Verify search_path was set
        mock_conn.execute.assert_called_once_with("SET search_path=discord,public")


@pytest.mark.asyncio
async def test_multiple_cogs_share_pool():
    """Test that multiple cogs can share the same pool."""
    from gentlebot import db

    # Create mock pool
    mock_pool = AsyncMock()
    mock_pool.is_closing = MagicMock(return_value=False)

    with patch.object(db.asyncpg, "create_pool", return_value=mock_pool) as mock_create:
        # Reset pool
        db._pool = None

        # Simulate multiple cogs getting the pool
        pool1 = await db.get_pool()
        pool2 = await db.get_pool()
        pool3 = await db.get_pool()

        # All should be the same instance
        assert pool1 is pool2
        assert pool2 is pool3

        # Pool should only be created once
        assert mock_create.call_count == 1
