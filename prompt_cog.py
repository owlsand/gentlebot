"""
prompt_cog.py – Dynamic Daily‑Ping Prompt Generator for Gentlebot
================================================================
Generates a rotating, AI-powered prompt each day via Hugging Face inference,
posts to DAILY_PING on schedule, and provides a command to skip to a new prompt.

Configuration in bot_config.py:
  • DAILY_PING: channel ID for daily‑ping
  • PROMPT_SCHEDULE_HOUR: (optional) local hour to schedule daily prompts
  • HF_API_TOKEN: required for HF inference
  • HF_MODEL: model ID for HF text-generation API
  • PROMPT_HISTORY_SIZE: how many past prompts to send as context
  • PROMPT_TEST_INTERVAL: (optional) seconds interval for test runs

Requires:
  • discord.py v2+
  • requests
  • huggingface-hub
  • zoneinfo (stdlib) or backports.zoneinfo
"""
from __future__ import annotations
import os
import random
from datetime import datetime, time, timezone
from collections import deque
from discord.ext import commands, tasks
from huggingface_hub import InferenceClient
import bot_config as cfg
from zoneinfo import ZoneInfo

# Timezone for scheduling
LOCAL_TZ = ZoneInfo("America/Los_Angeles")
SCHEDULE_HOUR = getattr(cfg, 'PROMPT_SCHEDULE_HOUR', 8)
DAILY_TIME = time(hour=SCHEDULE_HOUR, minute=0, tzinfo=LOCAL_TZ)

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
    """Scheduled and on‑demand AI-powered prompt generator with type rotation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        size = getattr(cfg, 'PROMPT_HISTORY_SIZE', 5)
        self.history = deque(maxlen=size)
        self.rotation_index = 0
        # Start the appropriate loop in cog_load

    def fetch_prompt(self) -> str:
        """Generate a new prompt via HF inference, including rotation and history."""
        # Rotate type
        prompt_type = PROMPT_TYPES[self.rotation_index]
        self.rotation_index = (self.rotation_index + 1) % len(PROMPT_TYPES)
        # Build messages
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
                print(f"PromptCog: inference error: {e}")
        # fallback
        prompt = random.choice(FALLBACK_PROMPTS)
        self.history.append(prompt)
        return prompt

    # Conditional loop decorator
    test_interval = os.getenv('PROMPT_TEST_INTERVAL')
    if test_interval:
        @tasks.loop(seconds=int(test_interval))
        async def daily_task(self):
            print(f"[PromptCog] test trigger at {datetime.now()}")
            await self._send_prompt()
    else:
        @tasks.loop(time=DAILY_TIME)
        async def daily_task(self):
            print(f"[PromptCog] scheduled trigger at {datetime.now()} PST/PDT")
            await self._send_prompt()

    async def _send_prompt(self):
        channel = self.bot.get_channel(cfg.DAILY_PING_CHANNEL)
        if not channel:
            return
        date_str = datetime.now(timezone.utc).strftime('%a, %b %d')
        prompt = self.fetch_prompt()
        await channel.send(f"{prompt}")

    @commands.command(name='skip_prompt')
    async def skip_prompt(self, ctx: commands.Context):
        date_str = datetime.now(timezone.utc).strftime('%a, %b %d')
        prompt = self.fetch_prompt()
        await ctx.send(f"{prompt}")

    def cog_load(self):
        # Start loop after cog is loaded
        self.daily_task.start()

async def setup(bot: commands.Bot):
    await bot.add_cog(PromptCog(bot))