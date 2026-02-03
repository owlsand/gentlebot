"""
tldr_cog.py – TL;DR Reactions for Long Messages
================================================
Provides on-demand summaries for long messages.

How it works:
  • Detects messages above a character threshold
  • Auto-reacts with 📝 emoji to indicate summary is available
  • When any user taps 📝, bot replies with 2-3 bullet summary
  • Caches summaries to avoid re-generating

Configuration in bot_config.py:
  • TLDR_ENABLED: Master toggle (default: True)
  • TLDR_MIN_LENGTH: Minimum characters to trigger (default: 500)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Tuple

import discord
from discord.ext import commands

from .. import bot_config as cfg
from ..llm.router import router, SafetyBlocked
from ..infra import RateLimited
from ..util import user_name
from ..capabilities import CogCapabilities, ReactionCapability

log = logging.getLogger(f"gentlebot.{__name__}")

# Emoji used to indicate TL;DR is available
TLDR_EMOJI = "📝"

# Minimum message length to trigger TL;DR reaction (characters)
DEFAULT_MIN_LENGTH = 500

# Cache for summaries to avoid repeated API calls
# Key: message_id, Value: (content, summary)
_tldr_cache: Dict[int, Tuple[str, str]] = {}

# Maximum cache size
MAX_CACHE_SIZE = 200


class TLDRCog(commands.Cog):
    """Provides TL;DR summaries for long messages via reaction interface."""

    CAPABILITIES = CogCapabilities(
        reactions=[
            ReactionCapability(
                emoji="📝",
                trigger="Long messages",
                description="React to get a 2-3 bullet summary of the message",
            ),
        ]
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.enabled = getattr(cfg, "TLDR_ENABLED", True)
        self.min_length = getattr(cfg, "TLDR_MIN_LENGTH", DEFAULT_MIN_LENGTH)

    async def _summarize_message(self, content: str, author_name: str) -> str:
        """Use LLM to summarize the message content."""
        prompt = f"""Summarize this Discord message into key bullet points.

Author: {author_name}

Message:
{content[:4000]}

Requirements:
- Return exactly 2-3 bullet points capturing the key points
- Start each bullet with "• " (bullet character)
- Each bullet should be one concise sentence
- Capture the main ideas, not every detail
- Keep total response under 300 characters
- Do NOT write paragraphs - bullets only"""

        try:
            response = await asyncio.to_thread(
                router.generate,
                "general",
                [{"role": "user", "content": prompt}],
                temperature=0.4,
            )
            return response.strip()
        except (RateLimited, SafetyBlocked):
            log.info("LLM unavailable for TL;DR summary")
            return "Summary unavailable. Try again later."
        except Exception:
            log.exception("Failed to generate TL;DR summary")
            return "Could not generate summary for this message."

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Detect long messages and add 📝 reaction."""
        # Skip if disabled
        if not self.enabled:
            return

        # Skip bots
        if message.author.bot:
            return

        # Check message length
        if len(message.content) < self.min_length:
            return

        log.info(
            "Detected long message (%d chars) from %s",
            len(message.content),
            user_name(message.author),
        )

        # Manage cache size
        global _tldr_cache
        if len(_tldr_cache) >= MAX_CACHE_SIZE:
            # Remove oldest entries
            oldest_keys = list(_tldr_cache.keys())[: MAX_CACHE_SIZE // 2]
            for k in oldest_keys:
                del _tldr_cache[k]

        # Store the content for later summarization
        _tldr_cache[message.id] = (message.content, "")

        # Add the TL;DR emoji reaction
        try:
            await message.add_reaction(TLDR_EMOJI)
        except discord.HTTPException:
            log.warning("Failed to add TL;DR emoji to message %s", message.id)

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        """Handle 📝 reaction to show TL;DR summary."""
        # Skip if disabled
        if not self.enabled:
            return

        # Only respond to TL;DR emoji
        if str(payload.emoji) != TLDR_EMOJI:
            return

        # Skip bot's own reactions
        if payload.user_id == self.bot.user.id:
            return

        # Check if we have cached data for this message
        cached = _tldr_cache.get(payload.message_id)
        if not cached:
            return

        content, existing_summary = cached

        # Get the channel and message
        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return
        except discord.HTTPException:
            log.warning("Failed to fetch message %s", payload.message_id)
            return

        # If we already have a summary, use it
        if existing_summary:
            summary = existing_summary
        else:
            # Generate summary
            author_name = user_name(message.author)
            summary = await self._summarize_message(content, author_name)

            # Cache the summary
            _tldr_cache[payload.message_id] = (content, summary)

        # Send the summary as a reply
        response = f"📝 **TL;DR**\n\n{summary}"

        try:
            await message.reply(response, mention_author=False)
            log.info(
                "Sent TL;DR summary for message from %s requested by user %s",
                user_name(message.author),
                payload.user_id,
            )

            # Remove from cache after sending to avoid duplicate responses
            _tldr_cache.pop(payload.message_id, None)
        except discord.HTTPException as exc:
            log.warning("Failed to send TL;DR summary: %s", exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TLDRCog(bot))
