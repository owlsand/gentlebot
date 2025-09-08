"""Ambient image generation reactions."""
from __future__ import annotations

import io
import asyncio
import random
import logging

import discord
from discord.ext import commands

from ..llm.router import router, SafetyBlocked
from ..infra.quotas import RateLimited

log = logging.getLogger(f"gentlebot.{__name__}")


class AmbientImageCog(commands.Cog):
    """Occasionally generate playful images inspired by channel chatter."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.trigger_chance = 0.005  # 0.5%

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if getattr(message.flags, "ephemeral", False):
            return
        if random.random() >= self.trigger_chance:
            return

        texts: list[str] = []
        async for m in message.channel.history(limit=20):
            if m.author.bot:
                continue
            texts.append(m.content.strip())
        texts.reverse()
        context = "\n".join(t for t in texts if t)
        if not context:
            return

        messages = [
            {
                "role": "user",
                "content": (
                    "Craft a short imaginative prompt for an artistic image "
                    "based on this conversation:\n"
                    f"{context}"
                ),
            }
        ]
        try:
            prompt = await asyncio.to_thread(router.generate, "general", messages)
        except RateLimited:
            log.info("Prompt generation rate limited")
            return
        except SafetyBlocked:
            log.info("Prompt generation blocked by safety policies")
            return
        except Exception:
            log.exception("Prompt generation failed")
            return

        if not prompt.strip():
            return
        try:
            data = await asyncio.to_thread(router.generate_image, prompt)
        except RateLimited:
            log.info("Image generation rate limited")
            return
        except SafetyBlocked:
            log.info("Image generation blocked by safety policies")
            return
        except Exception:
            log.exception("Ambient image generation failed")
            return
        if not data:
            return
        file = discord.File(io.BytesIO(data), filename="ambient.png")
        try:
            await message.channel.send(file=file)
        except Exception:
            log.exception("Failed to send ambient image")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AmbientImageCog(bot))
