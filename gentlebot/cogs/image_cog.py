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

    async def _send_friendly_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        """Reply with a friendly message about an error.

        This uses ``generate_content`` via ``router.generate`` to craft a short
        apology that includes the error details.  If that fails (for example due
        to quota limits) a generic fallback message is sent instead.
        """
        try:
            message = await asyncio.to_thread(
                router.generate,
                "general",
                [
                    {
                        "role": "user",
                        "content": (
                            "Write a brief friendly apology explaining that the"
                            f" image request failed because: {error}"
                        ),
                    }
                ],
            )
            await interaction.followup.send(message)
        except Exception:
            await interaction.followup.send(
                "Unfortunately I've exceeded quota and am being told to wait. "
                "Try again in a bit."
            )

    @app_commands.command(name="image", description="Generate an image with Gemini")
    async def image(self, interaction: discord.Interaction, prompt: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            data = await asyncio.to_thread(router.generate_image, prompt)
        except RateLimited as exc:
            await self._send_friendly_error(interaction, exc)
            return
        except SafetyBlocked:
            await interaction.followup.send(
                "Your inquiry is being blocked by my policy commitments.")
            return
        except Exception as exc:
            log.exception("Image generation failed")
            await self._send_friendly_error(interaction, exc)
            return
        if data:
            file = discord.File(io.BytesIO(data), filename="gemini.png")
            safe_prompt = prompt
            if len(prompt) > 1894:
                safe_prompt = prompt[:1891] + "..."
            message = f"||{safe_prompt}||"
            await interaction.followup.send(message, file=file)
        else:
            await interaction.followup.send("Image generation didn't work.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ImageCog(bot))
