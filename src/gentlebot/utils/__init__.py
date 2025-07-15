import discord

def chan_name(channel: discord.abc.Connectable | None) -> str:
    """Return a readable channel name or fallback to ID."""
    if channel is None:
        return "unknown"
    name = getattr(channel, "name", None)
    if name:
        return name
    channel_id = getattr(channel, "id", None)
    return str(channel_id) if channel_id is not None else "unknown"
