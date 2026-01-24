"""SQLite-backed state cache for restart-safe state persistence.

This module provides a lightweight, Pi-friendly alternative to Redis for
persisting state that needs to survive bot restarts.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(f"gentlebot.{__name__}")

DEFAULT_DB_PATH = Path("data/state.db")


class StateCache:
    """SQLite-backed key-value cache with TTL support.

    Example::

        cache = StateCache()
        await cache.set("last_trigger:burst", "2025-01-23T10:00:00", ttl_hours=24)
        value = await cache.get("last_trigger:burst")  # Returns the value or None

    This class is designed for simple key-value storage that needs to persist
    across bot restarts. It's not intended for high-throughput operations.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialize the state cache.

        Args:
            db_path: Path to the SQLite database file. Defaults to data/state.db.
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create the database and table if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state_cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_state_cache_expires ON state_cache(expires_at)"
            )
            conn.commit()

    def _now_utc(self) -> datetime:
        """Return current UTC time."""
        return datetime.now(timezone.utc)

    def get(self, key: str) -> Any | None:
        """Get a value from the cache.

        Args:
            key: The cache key.

        Returns:
            The cached value (JSON-decoded) or None if not found or expired.
        """
        with sqlite3.connect(self.db_path) as conn:
            # Clean up expired entries opportunistically
            conn.execute(
                "DELETE FROM state_cache WHERE expires_at IS NOT NULL AND expires_at < ?",
                (self._now_utc().isoformat(),),
            )
            conn.commit()

            cursor = conn.execute(
                """
                SELECT value FROM state_cache
                WHERE key = ?
                AND (expires_at IS NULL OR expires_at > ?)
                """,
                (key, self._now_utc().isoformat()),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return row[0]

    def set(
        self,
        key: str,
        value: Any,
        ttl_hours: float | None = None,
    ) -> None:
        """Set a value in the cache.

        Args:
            key: The cache key.
            value: The value to cache (will be JSON-encoded if not a string).
            ttl_hours: Optional time-to-live in hours. None means no expiration.
        """
        if isinstance(value, str):
            serialized = value
        else:
            serialized = json.dumps(value)

        expires_at = None
        if ttl_hours is not None:
            expires_at = (self._now_utc() + timedelta(hours=ttl_hours)).isoformat()

        now_iso = self._now_utc().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO state_cache (key, value, expires_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (key, serialized, expires_at, now_iso, now_iso),
            )
            conn.commit()

    def delete(self, key: str) -> bool:
        """Delete a value from the cache.

        Args:
            key: The cache key.

        Returns:
            True if a value was deleted, False otherwise.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM state_cache WHERE key = ?",
                (key,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def clear_expired(self) -> int:
        """Remove all expired entries from the cache.

        Returns:
            The number of entries removed.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM state_cache WHERE expires_at IS NOT NULL AND expires_at < ?",
                (self._now_utc().isoformat(),),
            )
            conn.commit()
            return cursor.rowcount

    def get_all_keys(self, prefix: str | None = None) -> list[str]:
        """Get all keys in the cache, optionally filtered by prefix.

        Args:
            prefix: Optional prefix to filter keys.

        Returns:
            List of matching keys.
        """
        with sqlite3.connect(self.db_path) as conn:
            if prefix:
                cursor = conn.execute(
                    """
                    SELECT key FROM state_cache
                    WHERE key LIKE ?
                    AND (expires_at IS NULL OR expires_at > ?)
                    """,
                    (f"{prefix}%", self._now_utc().isoformat()),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT key FROM state_cache
                    WHERE expires_at IS NULL OR expires_at > ?
                    """,
                    (self._now_utc().isoformat(),),
                )
            return [row[0] for row in cursor.fetchall()]


# Global instance for convenience
_default_cache: StateCache | None = None


def get_state_cache(db_path: Path | str | None = None) -> StateCache:
    """Get the global state cache instance.

    Args:
        db_path: Optional path to override the default database location.

    Returns:
        The StateCache instance.
    """
    global _default_cache
    if db_path is not None:
        return StateCache(db_path)
    if _default_cache is None:
        _default_cache = StateCache()
    return _default_cache
