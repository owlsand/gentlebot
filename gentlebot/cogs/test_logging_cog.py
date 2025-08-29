from __future__ import annotations
import logging

import discord
from discord.ext import commands
from ..util import chan_name, user_name

# Use the same logger as main.py so handlers are attached
log = logging.getLogger("gentlebot")

class TestLoggingCog(commands.Cog):
    """Extra verbose logging for test environment."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Log all registered slash commands."""
        for cmd in self.bot.tree.get_commands():
            log.info("[TEST] Loaded /%s", cmd.name)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type is discord.InteractionType.application_command:
            data = interaction.data or {}
            name = data.get("name")
            log.info(
                "[TEST] Slash command /%s by %s in %s",
                name,
                user_name(interaction.user),
                chan_name(interaction.channel),
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        log.info(
            "[TEST] Message from %s in %s: %s",
            user_name(message.author),
            chan_name(message.channel),
            message.content.replace("\n", " "),
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        log.info(
            "[TEST] Reaction %s added by %s to %s in %s",
            str(payload.emoji),
            user_name(self.bot.get_user(payload.user_id) or payload.user_id),
            payload.message_id,
            chan_name(self.bot.get_channel(payload.channel_id)),
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(TestLoggingCog(bot))
