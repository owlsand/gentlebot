import os
import logging
import discord

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

def chan_name(channel: discord.abc.Connectable | None) -> str:
    """Return a readable channel name or fallback to ID."""
    if channel is None:
        return "unknown"
    name = getattr(channel, "name", None)
    if name:
        return name
    channel_id = getattr(channel, "id", None)
    return str(channel_id) if channel_id is not None else "unknown"


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


def rows_from_tag(tag: str) -> int:
    """Return the affected row count from an asyncpg status tag."""
    try:
        return int(str(tag).split()[-1])
    except (IndexError, ValueError):
        return 0
