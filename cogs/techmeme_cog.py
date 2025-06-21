"""TechmemeCog – display the latest stories from Techmeme's RSS feed."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands
import feedparser

from util import chan_name

log = logging.getLogger(__name__)

TECHMEME_RSS = "https://www.techmeme.com/feed.xml"


class TechmemeCog(commands.Cog):
    """Slash command to show recent Techmeme headlines."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="techmeme", description="Show the latest Techmeme headlines")
    async def techmeme(self, interaction: discord.Interaction):
        log.info("/techmeme invoked by %s in %s", interaction.user.id, chan_name(interaction.channel))
        await interaction.response.defer(thinking=True)
        try:
            feed = await asyncio.to_thread(feedparser.parse, TECHMEME_RSS)
            entries = feed.entries[:5]
        except Exception:
            log.exception("Failed to fetch Techmeme RSS")
            await interaction.followup.send("Could not fetch Techmeme headlines right now.")
            return

        if not entries:
            await interaction.followup.send("No headlines found.")
            return

        lines = [f"[{e.title}]({e.link})" for e in entries]
        text = "\n".join(lines)
        if len(text) > 1900:
            text = text[:1895] + "…"

        embed = discord.Embed(title="Techmeme Top Stories", description=text, colour=0x4F90C4)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(TechmemeCog(bot))

