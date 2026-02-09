"""Shared engagement query functions for recap and stats features.

All functions accept an asyncpg.Pool and return structured data.
Each guards on ``pool is None`` and returns a sane default.
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg

log = logging.getLogger(f"gentlebot.{__name__}")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PRIVACY_JOIN = """
    JOIN discord.channel c ON m.channel_id = c.channel_id
"""

_PRIVACY_FILTER = """
    AND (c.is_private IS NOT TRUE)
    AND (c.nsfw IS FALSE OR c.nsfw IS NULL)
"""

_NON_BOT_JOIN = """
    JOIN discord."user" u ON m.author_id = u.user_id
"""

_NON_BOT_FILTER = """
    AND u.is_bot IS NOT TRUE
"""


# ===================================================================
# Server-wide queries (used by weekly recap)
# ===================================================================

async def server_message_count(pool: asyncpg.Pool | None, interval: str) -> int:
    """Total non-bot messages in public non-NSFW channels within *interval*."""
    if pool is None:
        return 0
    return await pool.fetchval(
        f"""
        SELECT COUNT(*)
        FROM discord.message m
        {_NON_BOT_JOIN}
        {_PRIVACY_JOIN}
        WHERE m.created_at >= now() - $1::interval
        {_NON_BOT_FILTER}
        {_PRIVACY_FILTER}
        """,
        interval,
    ) or 0


async def unique_posters(pool: asyncpg.Pool | None, interval: str) -> int:
    """Distinct author count in public channels within *interval*."""
    if pool is None:
        return 0
    return await pool.fetchval(
        f"""
        SELECT COUNT(DISTINCT m.author_id)
        FROM discord.message m
        {_NON_BOT_JOIN}
        {_PRIVACY_JOIN}
        WHERE m.created_at >= now() - $1::interval
        {_NON_BOT_FILTER}
        {_PRIVACY_FILTER}
        """,
        interval,
    ) or 0


async def top_posters(
    pool: asyncpg.Pool | None, interval: str, limit: int = 5,
) -> list[tuple[int, int]]:
    """Top posters as ``[(author_id, count)]`` sorted desc."""
    if pool is None:
        return []
    rows = await pool.fetch(
        f"""
        SELECT m.author_id, COUNT(*) AS cnt
        FROM discord.message m
        {_NON_BOT_JOIN}
        {_PRIVACY_JOIN}
        WHERE m.created_at >= now() - $1::interval
        {_NON_BOT_FILTER}
        {_PRIVACY_FILTER}
        GROUP BY m.author_id
        ORDER BY cnt DESC
        LIMIT $2
        """,
        interval,
        limit,
    )
    return [(r["author_id"], r["cnt"]) for r in rows]


async def top_reaction_receivers(
    pool: asyncpg.Pool | None, interval: str, limit: int = 5,
) -> list[tuple[int, int]]:
    """Top reaction receivers as ``[(author_id, reaction_count)]``."""
    if pool is None:
        return []
    rows = await pool.fetch(
        f"""
        SELECT m.author_id, COUNT(*) AS cnt
        FROM discord.reaction_event re
        JOIN discord.message m ON re.message_id = m.message_id
        {_NON_BOT_JOIN}
        {_PRIVACY_JOIN}
        WHERE re.event_at >= now() - $1::interval
          AND re.reaction_action = 'MESSAGE_REACTION_ADD'
        {_NON_BOT_FILTER}
        {_PRIVACY_FILTER}
        GROUP BY m.author_id
        ORDER BY cnt DESC
        LIMIT $2
        """,
        interval,
        limit,
    )
    return [(r["author_id"], r["cnt"]) for r in rows]


async def most_active_channels(
    pool: asyncpg.Pool | None, interval: str, limit: int = 5,
) -> list[tuple[int, str, int]]:
    """Most active channels as ``[(channel_id, name, count)]``."""
    if pool is None:
        return []
    rows = await pool.fetch(
        f"""
        SELECT c.channel_id, c.name, COUNT(*) AS cnt
        FROM discord.message m
        {_NON_BOT_JOIN}
        {_PRIVACY_JOIN}
        WHERE m.created_at >= now() - $1::interval
        {_NON_BOT_FILTER}
        {_PRIVACY_FILTER}
        GROUP BY c.channel_id, c.name
        ORDER BY cnt DESC
        LIMIT $2
        """,
        interval,
        limit,
    )
    return [(r["channel_id"], r["name"], r["cnt"]) for r in rows]


async def top_reacted_message(
    pool: asyncpg.Pool | None, interval: str,
) -> dict[str, Any] | None:
    """Single most-reacted message in the window.

    Returns ``{message_id, channel_id, channel_name, author_id, content,
    reaction_count}`` or *None*.
    """
    if pool is None:
        return None
    row = await pool.fetchrow(
        f"""
        SELECT m.message_id,
               m.channel_id,
               c.name AS channel_name,
               m.author_id,
               LEFT(m.content, 200) AS content,
               COUNT(*) AS reaction_count
        FROM discord.reaction_event re
        JOIN discord.message m ON re.message_id = m.message_id
        {_NON_BOT_JOIN}
        {_PRIVACY_JOIN}
        WHERE re.event_at >= now() - $1::interval
          AND re.reaction_action = 'MESSAGE_REACTION_ADD'
        {_NON_BOT_FILTER}
        {_PRIVACY_FILTER}
        GROUP BY m.message_id, m.channel_id, c.name, m.author_id, m.content
        ORDER BY reaction_count DESC
        LIMIT 1
        """,
        interval,
    )
    if row is None:
        return None
    return dict(row)


async def new_member_count(pool: asyncpg.Pool | None, interval: str) -> int:
    """Users with ``first_seen_at`` in window."""
    if pool is None:
        return 0
    return await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM discord."user"
        WHERE first_seen_at >= now() - $1::interval
          AND is_bot IS NOT TRUE
        """,
        interval,
    ) or 0


async def active_streak_counts(
    pool: asyncpg.Pool | None,
) -> tuple[int, int]:
    """Return ``(total_active, strong_7plus)`` from ``user_streak``."""
    if pool is None:
        return (0, 0)
    row = await pool.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE current_streak > 0) AS total_active,
            COUNT(*) FILTER (WHERE current_streak >= 7) AS strong
        FROM discord.user_streak
        """,
    )
    if row is None:
        return (0, 0)
    return (row["total_active"], row["strong"])


async def new_hof_count(pool: asyncpg.Pool | None, interval: str) -> int:
    """Hall of fame inductions in window."""
    if pool is None:
        return 0
    return await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM discord.hall_of_fame
        WHERE inducted_at >= now() - $1::interval
          AND inducted_at IS NOT NULL
        """,
        interval,
    ) or 0


# ===================================================================
# User-specific queries (used by /mystats)
# ===================================================================

async def user_message_count(
    pool: asyncpg.Pool | None, user_id: int, interval: str,
) -> int:
    """Message count for one user in public channels within *interval*."""
    if pool is None:
        return 0
    return await pool.fetchval(
        f"""
        SELECT COUNT(*)
        FROM discord.message m
        {_PRIVACY_JOIN}
        WHERE m.author_id = $1
          AND m.created_at >= now() - $2::interval
        {_PRIVACY_FILTER}
        """,
        user_id,
        interval,
    ) or 0


async def user_message_percentile(
    pool: asyncpg.Pool | None, user_id: int, interval: str,
) -> float | None:
    """Percentile rank among all posters (0.0–1.0).

    Returns *None* if the user has no messages in the window.
    """
    if pool is None:
        return None
    return await pool.fetchval(
        f"""
        WITH poster_counts AS (
            SELECT m.author_id, COUNT(*) AS cnt
            FROM discord.message m
            {_NON_BOT_JOIN}
            {_PRIVACY_JOIN}
            WHERE m.created_at >= now() - $2::interval
            {_NON_BOT_FILTER}
            {_PRIVACY_FILTER}
            GROUP BY m.author_id
        )
        SELECT PERCENT_RANK() OVER (ORDER BY cnt) AS pct
        FROM poster_counts
        WHERE author_id = $1
        """,
        user_id,
        interval,
    )


async def user_reactions_received(
    pool: asyncpg.Pool | None, user_id: int, interval: str,
) -> int:
    """Total ADD reactions on a user's messages in the window."""
    if pool is None:
        return 0
    return await pool.fetchval(
        f"""
        SELECT COUNT(*)
        FROM discord.reaction_event re
        JOIN discord.message m ON re.message_id = m.message_id
        {_PRIVACY_JOIN}
        WHERE m.author_id = $1
          AND re.event_at >= now() - $2::interval
          AND re.reaction_action = 'MESSAGE_REACTION_ADD'
        {_PRIVACY_FILTER}
        """,
        user_id,
        interval,
    ) or 0


async def user_top_emojis_received(
    pool: asyncpg.Pool | None, user_id: int, interval: str, limit: int = 5,
) -> list[tuple[str, int]]:
    """Top emojis received as ``[(emoji, count)]``."""
    if pool is None:
        return []
    rows = await pool.fetch(
        f"""
        SELECT re.emoji, COUNT(*) AS cnt
        FROM discord.reaction_event re
        JOIN discord.message m ON re.message_id = m.message_id
        {_PRIVACY_JOIN}
        WHERE m.author_id = $1
          AND re.event_at >= now() - $2::interval
          AND re.reaction_action = 'MESSAGE_REACTION_ADD'
        {_PRIVACY_FILTER}
        GROUP BY re.emoji
        ORDER BY cnt DESC
        LIMIT $3
        """,
        user_id,
        interval,
        limit,
    )
    return [(r["emoji"], r["cnt"]) for r in rows]


async def user_top_channels(
    pool: asyncpg.Pool | None, user_id: int, interval: str, limit: int = 3,
) -> list[tuple[int, str, int]]:
    """User's most-posted channels as ``[(channel_id, name, count)]``."""
    if pool is None:
        return []
    rows = await pool.fetch(
        f"""
        SELECT c.channel_id, c.name, COUNT(*) AS cnt
        FROM discord.message m
        {_PRIVACY_JOIN}
        WHERE m.author_id = $1
          AND m.created_at >= now() - $2::interval
        {_PRIVACY_FILTER}
        GROUP BY c.channel_id, c.name
        ORDER BY cnt DESC
        LIMIT $3
        """,
        user_id,
        interval,
        limit,
    )
    return [(r["channel_id"], r["name"], r["cnt"]) for r in rows]


async def user_peak_hour(
    pool: asyncpg.Pool | None, user_id: int, interval: str,
) -> int | None:
    """Most active hour of day in LA timezone. Returns 0–23 or *None*."""
    if pool is None:
        return None
    return await pool.fetchval(
        f"""
        SELECT EXTRACT(HOUR FROM m.created_at AT TIME ZONE 'America/Los_Angeles')::int AS hr
        FROM discord.message m
        {_PRIVACY_JOIN}
        WHERE m.author_id = $1
          AND m.created_at >= now() - $2::interval
        {_PRIVACY_FILTER}
        GROUP BY hr
        ORDER BY COUNT(*) DESC
        LIMIT 1
        """,
        user_id,
        interval,
    )


async def user_hall_of_fame_count(
    pool: asyncpg.Pool | None, user_id: int,
) -> int:
    """Inducted HoF entries for a user."""
    if pool is None:
        return 0
    return await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM discord.hall_of_fame
        WHERE author_id = $1
          AND inducted_at IS NOT NULL
        """,
        user_id,
    ) or 0


async def user_fun_facts(
    pool: asyncpg.Pool | None, user_id: int,
) -> dict[str, Any]:
    """Fun facts: ``{first_seen_at, lifetime_messages, longest_message_len}``."""
    if pool is None:
        return {"first_seen_at": None, "lifetime_messages": 0, "longest_message_len": 0}
    row = await pool.fetchrow(
        """
        SELECT
            u.first_seen_at,
            COUNT(m.message_id) AS lifetime_messages,
            COALESCE(MAX(LENGTH(m.content)), 0) AS longest_message_len
        FROM discord."user" u
        LEFT JOIN discord.message m ON m.author_id = u.user_id
        WHERE u.user_id = $1
        GROUP BY u.user_id, u.first_seen_at
        """,
        user_id,
    )
    if row is None:
        return {"first_seen_at": None, "lifetime_messages": 0, "longest_message_len": 0}
    return dict(row)


async def user_reaction_percentile(
    pool: asyncpg.Pool | None, user_id: int, interval: str,
) -> float | None:
    """Percentile rank for reactions received among all message authors.

    Returns *None* if the user received no reactions in the window.
    """
    if pool is None:
        return None
    return await pool.fetchval(
        f"""
        WITH author_reacts AS (
            SELECT m.author_id, COUNT(*) AS cnt
            FROM discord.reaction_event re
            JOIN discord.message m ON re.message_id = m.message_id
            {_NON_BOT_JOIN}
            {_PRIVACY_JOIN}
            WHERE re.event_at >= now() - $2::interval
              AND re.reaction_action = 'MESSAGE_REACTION_ADD'
            {_NON_BOT_FILTER}
            {_PRIVACY_FILTER}
            GROUP BY m.author_id
        )
        SELECT PERCENT_RANK() OVER (ORDER BY cnt) AS pct
        FROM author_reacts
        WHERE author_id = $1
        """,
        user_id,
        interval,
    )
