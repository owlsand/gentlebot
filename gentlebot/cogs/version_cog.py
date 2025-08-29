"""
version_cog.py – Simple version info command for Gentlebot
==========================================================
Provides a slash command `/version` that returns the current Git commit
hash for debugging purposes.
"""
from __future__ import annotations

import logging
import discord
from discord import app_commands
from discord.ext import commands

from ..version import VERSION
from ..util import chan_name, user_name

# Use a hierarchical logger so messages propagate to the main gentlebot logger
log = logging.getLogger(f"gentlebot.{__name__}")


class VersionCog(commands.Cog):
    """Slash command to show the running Gentlebot version."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="version", description="Show the current bot version")
    async def version(self, interaction: discord.Interaction):
        """Reply with the Git commit hash of the running bot."""
        log.info(
            "/version invoked by %s in %s",
            user_name(interaction.user),
            chan_name(interaction.channel),
        )
        await interaction.response.send_message(
            f"Gentlebot version: {VERSION}", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(VersionCog(bot))
