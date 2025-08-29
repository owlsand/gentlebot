"""Summarize missed conversations for returning users."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands
from ..db import get_pool
from ..llm.router import router, SafetyBlocked
from ..infra.quotas import RateLimited

log = logging.getLogger(f"gentlebot.{__name__}")


class CatchupCog(commands.Cog):
    """Provide a `/catchup` slash command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.max_tokens = 200
        self.temperature = 0.6
        self.pool: asyncpg.Pool | None = None

    async def cog_load(self) -> None:
        try:
            self.pool = await get_pool()
        except RuntimeError:
            log.warning("CatchupCog disabled due to missing database URL")
            self.pool = None

    async def cog_unload(self) -> None:
        self.pool = None

    async def _collect_messages(
        self, interaction: discord.Interaction, scope: str
    ) -> list[str]:
        if not self.pool:
            return []
        user = interaction.user
        row = await self.pool.fetchrow(
            'SELECT last_seen_at FROM discord."user" WHERE user_id=$1',
            user.id,
        )
        last_seen = row["last_seen_at"] if row and row["last_seen_at"] else None
        if last_seen is None:
            last_seen = discord.utils.utcnow() - timedelta(days=1)

        params: list[object] = [last_seen, user.id]
        query = (
            "SELECT m.content, m.channel_id, c.name AS channel_name, u.display_name "
            "FROM discord.message m "
            "JOIN discord.channel c ON m.channel_id = c.channel_id "
            "JOIN discord.\"user\" u ON m.author_id = u.user_id "
            "WHERE m.created_at >= $1 AND m.author_id <> $2"
        )
        idx = 3
        if scope == "channel":
            channel_id = getattr(interaction.channel, "id", None)
            if channel_id is None:
                return []
            query += f" AND m.channel_id = ${idx}"
            params.append(channel_id)
            idx += 1
        elif scope == "mentions":
            query += f" AND m.mentions::jsonb @> to_jsonb(array[${idx}]::bigint[])"
            params.append(user.id)
            idx += 1
        query += " ORDER BY m.created_at ASC LIMIT 100"
        rows = await self.pool.fetch(query, *params)
        prefix = scope != "channel"
        messages = []
        for r in rows:
            author = r["display_name"] or "?"
            content = r["content"] or ""
            channel_name = r["channel_name"] or str(r["channel_id"])
            if prefix:
                messages.append(f"[#{channel_name}] {author}: {content}")
            else:
                messages.append(f"{author}: {content}")
        return messages

    async def _summarize(self, messages: list[str], style: str | None) -> str:
        convo = "\n".join(messages)
        system = "Summarize the following messages for a user who has been away. Be concise."
        if style:
            system += f" Use the following style or tone: {style}."
        data = [
            {"role": "system", "content": system},
            {"role": "user", "content": convo},
        ]
        try:
            return await asyncio.to_thread(
                router.generate, "general", data, self.temperature
            )
        except RateLimited:
            return "Let me get back to you on this... I'm a bit busy right now."
        except SafetyBlocked:
            return "Your inquiry is being blocked by my policy commitments."
        except Exception as exc:
            log.exception("Summarization failed: %s", exc)
            return "Something's wrong... I need a mechanic."

    @app_commands.command(name="catchup", description="Summarize conversations since you were last online.")
    @app_commands.describe(
        visibility="Who should see the summary",
        scope="Which messages to summarize",
        style="Optional style or tone for the summary",
    )
    @app_commands.choices(
        visibility=[
            app_commands.Choice(name="only me", value="only me"),
            app_commands.Choice(name="everyone", value="everyone"),
        ],
        scope=[
            app_commands.Choice(name="all", value="all"),
            app_commands.Choice(name="channel", value="channel"),
            app_commands.Choice(name="mentions", value="mentions"),
        ],
    )
    async def catchup(
        self,
        interaction: discord.Interaction,
        visibility: str = "everyone",
        scope: str = "all",
        style: str | None = None,
    ) -> None:
        """Summarize recent messages for the invoking user."""
        ephemeral = visibility == "only me"
        messages = await self._collect_messages(interaction, scope)
        if not messages:
            await interaction.response.send_message(
                "No new messages to summarize.", ephemeral=ephemeral
            )
            return
        try:
            summary = await self._summarize(messages, style)
        except Exception as exc:
            log.exception("Gemini summarization failed: %s", exc)
            summary = "⚠️ Unable to generate summary at this time."
        await interaction.response.send_message(summary[:1900], ephemeral=ephemeral)


async def setup(bot: commands.Bot) -> None:
    """Load the cog."""
    await bot.add_cog(CatchupCog(bot))
