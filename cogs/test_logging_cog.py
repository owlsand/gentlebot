from __future__ import annotations
import logging

import discord
from discord.ext import commands

log = logging.getLogger(__name__)

class TestLoggingCog(commands.Cog):
    """Extra verbose logging for test environment."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type is discord.InteractionType.application_command:
            data = interaction.data or {}
            name = data.get("name")
            log.info("[TEST] Slash command /%s by %s in %s", name, interaction.user.id, getattr(interaction.channel, "name", interaction.channel_id))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        log.info("[TEST] Message from %s in %s: %s", message.author.id, getattr(message.channel, "name", message.channel.id), message.content.replace('\n', ' '))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        log.info(
            "[TEST] Reaction %s added by %s to %s in %s",
            str(payload.emoji),
            payload.user_id,
            payload.message_id,
            payload.channel_id,
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(TestLoggingCog(bot))
