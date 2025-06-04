"""
prompt_cog.py – Dynamic Daily‑Ping Prompt Generator for Gentlebot
================================================================
Generates a rotating, AI-powered prompt each day via Hugging Face inference,
posts to DAILY_PING on schedule, and provides a command to skip to a new prompt.

Configuration in bot_config.py:
  • DAILY_PING_CHANNEL: channel ID for daily‑ping (must be an integer)
  • PROMPT_SCHEDULE_HOUR: (optional) local hour to schedule daily prompts
  • HF_API_TOKEN: required for HF inference
  • HF_MODEL: model ID for HF text-generation API
  • PROMPT_HISTORY_SIZE: how many past prompts to send as context

Requires:
  • discord.py v2+
  • requests
  • huggingface-hub
  • zoneinfo (stdlib) or backports.zoneinfo
"""
from __future__ import annotations
import os
import random
import asyncio
import logging
from datetime import datetime, time, timedelta
from collections import deque
from discord.ext import commands
from huggingface_hub import InferenceClient
import bot_config as cfg
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

# Timezone for scheduling
LOCAL_TZ = ZoneInfo("America/Los_Angeles")
SCHEDULE_HOUR = getattr(cfg, 'PROMPT_SCHEDULE_HOUR', 8)

# Fallback prompts
FALLBACK_PROMPTS = [
    "What's a book you think everyone should read?",
    "If you could instantly learn any language, which would it be and why?",
    "Share the last photo you took and tell us the story behind it.",
    "What’s a habit you’ve picked up this year that’s improved your life?",
    "What’s the weirdest fact you know?",
    "Describe your dream vacation in three words.",
]

# Prompt types for rotation
PROMPT_TYPES = [
    "Would You Rather – binary tradeoffs, real or hypothetical",
    "Reflection – introspective or self-insight",
    "Philosophical – abstract or existential",
    "Silly – absurd, humorous, or playful hypotheticals",
    "Identity – about self-concept, preferences, or roles",
    "Moral Dilemma – ethics-based, value-conflict scenarios",
    "Prediction – future-focused or speculative questions",
    "Recommendation – asks for advice, tips, or endorsements",
    "Nostalgia – memory-based or childhood-related prompts",
    "Hot Take – bold, opinionated, or contrarian statements",
]

class PromptCog(commands.Cog):
    """Scheduled and on‑demand AI-powered prompt generator with type rotation and custom scheduler."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        size = getattr(cfg, 'PROMPT_HISTORY_SIZE', 5)
        self.history = deque(maxlen=size)
        # Start with a random prompt type index
        self.rotation_index = random.randrange(len(PROMPT_TYPES))
        self._scheduler_task = None

    def fetch_prompt(self) -> str:
        """Generate a new prompt via HF inference, including rotation and history."""
        prompt_type = PROMPT_TYPES[self.rotation_index]
        self.rotation_index = (self.rotation_index + 1) % len(PROMPT_TYPES)
        messages = [
            {'role': 'system', 'content': 'You generate creative discussion prompts for a friendly Discord group. Your personality should be that of a robot butler with an almost imperceptibly subtle sardonic wit.'}
        ]
        messages += [{'role': 'assistant', 'content': p} for p in self.history]
        messages.append({'role': 'user', 'content': f"Generate one concise '{prompt_type}' prompt. Respond only with the prompt. Don't include quotation marks."})
        token = os.getenv('HF_API_TOKEN')
        if token:
            client = InferenceClient(provider="together", api_key=token)
            model = os.getenv('HF_MODEL', 'deepseek-ai/DeepSeek-R1')
            params = {
                'max_tokens': int(os.getenv('HF_MAX_TOKENS', 50)),
                'temperature': float(os.getenv('HF_TEMPERATURE', 0.8)),
                'top_p': float(os.getenv('HF_TOP_P', 0.9)),
            }
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    **params
                )
                content = getattr(completion.choices[0].message, 'content', None)
                if content:
                    prompt = content.strip()
                    self.history.append(prompt)
                    return prompt
            except Exception as e:
                log.exception("inference error: %s", e)
        prompt = random.choice(FALLBACK_PROMPTS)
        self.history.append(prompt)
        return prompt

    async def _send_prompt(self):
        # Retrieve and cast channel ID
        raw_channel = getattr(cfg, 'DAILY_PING_CHANNEL', None)
        try:
            channel_id = int(raw_channel) if raw_channel is not None else None
        except (TypeError, ValueError):
            log.error("DAILY_PING_CHANNEL invalid: %s", raw_channel)
            return
        if channel_id is None:
            log.error("DAILY_PING_CHANNEL not set in config.")
            return
        channel = self.bot.get_channel(channel_id)
        if not channel:
            log.error("Unable to find channel with ID %s", channel_id)
            return
        prompt = self.fetch_prompt()
        await channel.send(f"{prompt}")

    async def _scheduler(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            now = datetime.now(LOCAL_TZ)
            # Calculate next run at SCHEDULE_HOUR:00 local
            next_run = now.replace(hour=SCHEDULE_HOUR, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            # Log next scheduled time
            formatted = next_run.strftime("%I:%M:%S %p %Z").lstrip('0')
            log.info("Next prompt scheduled at %s", formatted)
            # Sleep until then
            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            # Time to send prompt
            log.info("firing scheduled prompt at %s", datetime.now(LOCAL_TZ).strftime("%I:%M:%S %p %Z"))
            await self._send_prompt()
            # Loop continues to schedule next day

    @commands.Cog.listener()
    async def on_ready(self):
        # Start scheduler once
        if self._scheduler_task is None:
            log.info("Starting scheduler task.")
            self._scheduler_task = self.bot.loop.create_task(self._scheduler())

    @commands.command(name='skip_prompt')
    async def skip_prompt(self, ctx: commands.Context):
        log.info("skip_prompt invoked by %s in %s", ctx.author.id, getattr(ctx.channel, "name", ctx.channel.id))
        prompt = self.fetch_prompt()
        await ctx.send(f"{prompt}")

async def setup(bot: commands.Bot):
    await bot.add_cog(PromptCog(bot))
