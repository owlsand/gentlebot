"""Image generation commands."""
from __future__ import annotations

import io
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..llm.router import router, SafetyBlocked
from ..infra.quotas import RateLimited

log = logging.getLogger(f"gentlebot.{__name__}")


class ImageCog(commands.Cog):
    """Expose an /image command using Gemini."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="image", description="Generate an image with Gemini")
    async def image(self, interaction: discord.Interaction, prompt: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            data = await asyncio.to_thread(router.generate_image, prompt)
        except RateLimited:
            await interaction.followup.send(
                "Let me get back to you on this... I'm a bit busy right now.")
            return
        except SafetyBlocked:
            await interaction.followup.send(
                "Your inquiry is being blocked by my policy commitments.")
            return
        except Exception:
            log.exception("Image generation failed")
            await interaction.followup.send("Something's wrong... I need a mechanic.")
            return
        if data:
            file = discord.File(io.BytesIO(data), filename="gemini.png")
            await interaction.followup.send(file=file)
        else:
            await interaction.followup.send("Image generation didn't work.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ImageCog(bot))
