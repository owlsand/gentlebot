import os
import logging
from enum import IntEnum
import discord


class ReactionAction(IntEnum):
    """Values matching Discord's reaction gateway events."""

    MESSAGE_REACTION_ADD = 0
    MESSAGE_REACTION_REMOVE = 1


def build_db_url() -> str | None:
    """Return a Postgres DSN built from env vars."""
    url = os.getenv("PG_DSN") or os.getenv("DATABASE_URL")
    if url:
        return url
    user = os.getenv("PG_USER")
    pwd = os.getenv("PG_PASSWORD")
    db = os.getenv("PG_DB")
    if user and pwd and db:
        return f"postgresql+asyncpg://{user}:{pwd}@db:5432/{db}"
    return None


def user_name(user: discord.abc.Snowflake | int | None) -> str:
    """Return a user's display name or fallback to their ID."""
    if user is None:
        return "unknown"
    if isinstance(user, int):
        return str(user)
    name = getattr(user, "display_name", None) or getattr(user, "name", None)
    if name:
        return name
    uid = getattr(user, "id", None)
    return str(uid) if uid is not None else "unknown"


def chan_name(channel: discord.abc.Connectable | None) -> str:
    """Return a readable channel name or fallback to ID."""
    if channel is None:
        return "unknown"
    name = getattr(channel, "name", None)
    if name:
        return f"#{name}"
    recipient = getattr(channel, "recipient", None)
    if recipient:
        return f"DM with {user_name(recipient)}"
    channel_id = getattr(channel, "id", None)
    return str(channel_id) if channel_id is not None else "unknown"


def guild_name(guild: discord.abc.Snowflake | int | None) -> str:
    """Return a guild's name or fallback to ID."""
    if guild is None:
        return "unknown"
    if isinstance(guild, int):
        return str(guild)
    name = getattr(guild, "name", None)
    if name:
        return name
    gid = getattr(guild, "id", None)
    return str(gid) if gid is not None else "unknown"


def int_env(var: str, default: int = 0) -> int:
    """Return int value from ENV or default if unset or invalid."""
    value = os.getenv(var)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        logging.getLogger(__name__).warning(
            "Invalid integer for %s: %s; using %s", var, value, default
        )
        return default


def bool_env(var: str, default: bool = False) -> bool:
    """Return boolean value from ENV or default if unset or invalid."""
    value = os.getenv(var)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    logging.getLogger(__name__).warning(
        "Invalid boolean for %s: %s; using %s", var, value, default
    )
    return default


def rows_from_tag(tag: str) -> int:
    """Return the affected row count from an asyncpg status tag."""
    try:
        return int(str(tag).split()[-1])
    except (IndexError, ValueError):
        return 0
