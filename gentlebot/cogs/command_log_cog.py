"""Log slash command invocations to Postgres."""
from __future__ import annotations

import json
import logging
import os

import asyncpg
import discord
from discord.ext import commands

from ..db import get_pool

log = logging.getLogger(f"gentlebot.{__name__}")


class CommandLogCog(commands.Cog):
    """Persist slash command usage statistics."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: asyncpg.Pool | None = None
        self.enabled = os.getenv("LOG_COMMANDS") == "1"

    async def cog_load(self) -> None:
        if not self.enabled:
            return
        try:
            self.pool = await get_pool()
        except RuntimeError:
            log.warning("LOG_COMMANDS set but PG_DSN is missing")
            self.enabled = False
            return
        log.info("Command logging enabled")

    async def cog_unload(self) -> None:
        self.pool = None

    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: discord.app_commands.Command
    ) -> None:
        if not self.enabled or not self.pool:
            return
        opts = interaction.data.get("options", []) if interaction.data else []
        await self.pool.execute(
            """
            INSERT INTO discord.command_invocations (
                guild_id, channel_id, user_id, command, args_json
            ) VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT ON CONSTRAINT uniq_cmd_inv_guild_chan_user_cmd_ts DO NOTHING
            """,
            interaction.guild_id,
            interaction.channel_id,
            interaction.user.id,
            command.name,
            json.dumps(opts),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(CommandLogCog(bot))
