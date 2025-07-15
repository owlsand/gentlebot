import os
import discord

def build_db_url() -> str | None:
    """Return a Postgres DSN built from env vars."""
    url = os.getenv("DATABASE_URL")
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
