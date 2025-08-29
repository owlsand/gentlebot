"""Admin slash command to echo text in a channel.

Provides an ephemeral `/gentlebot` command allowing administrators to send
arbitrary messages as the bot.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..util import chan_name, user_name

log = logging.getLogger(f"gentlebot.{__name__}")


class GentlebotCog(commands.Cog):
    """Cog implementing the admin-only `/gentlebot` command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gentlebot", description="Send a message as Gentlebot")
    @app_commands.describe(say="Text for Gentlebot to echo")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def gentlebot(self, interaction: discord.Interaction, say: str):
        """Echo the supplied text into the current channel."""
        log.info(
            "/gentlebot invoked by %s in %s: %s",
            user_name(interaction.user),
            chan_name(interaction.channel),
            say,
        )
        await interaction.response.defer(thinking=True, ephemeral=True)
        await interaction.channel.send(say[:1900])
        await interaction.followup.send("Message sent.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GentlebotCog(bot))
