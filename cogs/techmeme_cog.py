"""TechmemeCog – display the latest stories from Techmeme's RSS feed."""
from __future__ import annotations

import asyncio
import logging
import html
import re
from datetime import datetime, timezone

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
    @app_commands.describe(ephemeral="Whether the response should be ephemeral")
    async def techmeme(self, interaction: discord.Interaction, ephemeral: bool = False):
        log.info("/techmeme invoked by %s in %s", interaction.user.id, chan_name(interaction.channel))
        await interaction.response.defer(thinking=True, ephemeral=ephemeral)
        try:
            feed = await asyncio.to_thread(feedparser.parse, TECHMEME_RSS)
            entries = feed.entries[:5]
        except Exception:
            log.exception("Failed to fetch Techmeme RSS")
            await interaction.followup.send(
                "Could not fetch Techmeme headlines right now.", ephemeral=ephemeral
            )
            return

        if not entries:
            await interaction.followup.send("No headlines found.", ephemeral=ephemeral)
            return

        lines = []
        for i, e in enumerate(entries, start=1):
            title = e.title
            summary = re.sub(r"<[^>]+>", "", getattr(e, "summary", ""))
            summary = html.unescape(summary).replace("\n", " ").strip()
            lines.append(f"**{i}.** [{title}]({e.link}) - {summary}")

        text = "\n".join(lines)

        date_str = datetime.now(timezone.utc).strftime("%b %d")
        embed = discord.Embed(
            title=f"Techmeme Stories ({date_str})",
            description=text,
            color=discord.Color.blue(),
        )
        embed.set_footer(text="techmeme.com")
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)


async def setup(bot: commands.Bot):
    await bot.add_cog(TechmemeCog(bot))

