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
import json
from pathlib import Path
from datetime import datetime, time, timedelta
from collections import deque
from discord.ext import commands
from ..util import chan_name, int_env
from huggingface_hub import InferenceClient
from .. import bot_config as cfg
from zoneinfo import ZoneInfo

# Use a hierarchical logger so messages propagate to the main gentlebot logger
log = logging.getLogger(f"gentlebot.{__name__}")

# Timezone for scheduling
LOCAL_TZ = ZoneInfo("America/Los_Angeles")
SCHEDULE_HOUR = getattr(cfg, 'PROMPT_SCHEDULE_HOUR', 8)

# Path for persisting prompt rotation state
STATE_FILE = Path('prompt_state.json')
# How many recent prompt types to avoid repeating
RECENT_TYPE_COUNT = 3

# Fallback prompts
FALLBACK_PROMPTS = [
    "If happiness was the national currency, what kind of work would make you rich?",
    "What's a belief you've recently changed your mind about?",
    "Do we have free will, or is everything predetermined?",
    "Would society benefit more from truth at all costs or kindness at all costs?",
    "What is one lesson you feel you learned too late in life?",
    "How would humanity change if all humans lived to be 500 years old?",
    "Is ignorance truly bliss?",
    "Can morality exist independently of religion?",
    "Would immortality be a gift or a curse?",
    "Does art imitate life, or does life imitate art?",
    "What's something you've accomplished that your younger self wouldn't believe?",
    "What's one thing about your childhood you'd like to recreate as an adult?",
    "If you could instantly master one skill, what would it be?",
    "How do you recharge when you're emotionally drained?",
    "What would your life look like if you had zero fear of failure?",
    "Who is someone you're grateful to have in your life, and why?",
    "What’s a personal boundary you've set recently?",
    "What's your most unusual comfort food?",
    "Describe a perfect Sunday afternoon.",
    "How do you define personal success?",
    "If you could live in any fictional world, which would you choose and why?",
    "Imagine a world where people age backward. How would society adapt?",
    "If you could teleport anywhere right now, where would you go?",
    "If your life had a soundtrack, what would be the theme song?",
    "If you could design a planet from scratch, what unique features would it have?",
    "If you could experience someone else’s memory, whose would it be?",
    "You wake up tomorrow fluent in a new language. Which language and why?",
    "If colors had tastes, what flavor would blue be?",
    "You get to write one law everyone must follow. What's your law?",
    "Imagine you could have dinner with a historical figure—who and why?",
    "What’s your favorite harmless conspiracy theory?",
    "If animals could talk, which species would be the most annoying?",
    "What's your favorite weird food combination?",
    "What's an embarrassing story you're willing to share?",
    "What's the funniest misunderstanding you've ever experienced?",
    "If your life was a movie, who would narrate it?",
    "Which emoji do you secretly wish existed?",
    "If your pet could text you, what would their messages look like?",
    "What is the most overrated snack?",
    "Describe your personality as a type of bread.",
    "What's your favorite morning ritual?",
    "How do you keep your life organized?",
    "What's one thing you bought that improved your quality of life significantly?",
    "What's a trend you resisted but later enjoyed?",
    "Do you prefer routine or spontaneity in your day-to-day life?",
    "What’s one underrated habit that changed your life for the better?",
    "What's your ideal way to spend a vacation day?",
    "What’s something small you do that brings you consistent joy?",
    "If you could simplify one aspect of your life immediately, what would it be?",
    "Describe your perfect workspace setup.",
    "What current technology feels like magic to you?",
    "How would you feel if AI started managing all your communications?",
    "If you could invent a new gadget, what problem would it solve?",
    "What's a piece of technology you think humanity might regret inventing?",
    "If you had the power to control technology for one day, what would you do?",
    "Which future innovation do you look forward to most?",
    "What’s one way technology has unexpectedly improved your life?",
    "Should humans colonize other planets, or fix Earth first?",
    "What tech product would you redesign completely?",
    "How do you think the internet has changed your personality?",
    "What's the last movie or show that genuinely surprised you?",
    "If you could erase one film or book from your memory to experience it fresh again, which would it be?",
    "What's your guilty pleasure TV show or movie?",
    "What band or musician has influenced you most?",
    "What’s a book you think everyone should read at least once?",
    "Which fictional character do you identify with the most?",
    "If you could host your own podcast, what would the main theme be?",
    "Recommend a hidden gem (book, movie, or music).",
    "What's the best live event you've ever attended?",
    "What's an unpopular entertainment opinion you strongly hold?",
    "What makes you feel immediately connected to someone new?",
    "What quality do you value most in a friendship?",
    "What's something you wish your community did better?",
    "How do you navigate disagreements with people you care about?",
    "What's a memorable act of kindness someone did for you?",
    "How important are shared interests vs. shared values in friendships?",
    "What's one thing people misunderstand about you?",
    "How do you show appreciation to the people you care about?",
    "When do you feel most connected to your community?",
    "What's a lesson a friend taught you without realizing it?",
    "What's the best professional advice you've ever received?",
    "What motivates you beyond money and recognition?",
    "If you didn't have to work for money, what would you do instead?",
    "How do you know when it’s time to change jobs or careers?",
    "What's a professional mistake you learned the most from?",
    "Describe your ideal work culture.",
    "How do you stay curious and continuously learn in your profession?",
    "What's one thing your current career taught you about yourself?",
    "How would your ideal workday look?",
    "What's a professional achievement you're especially proud of?",
    "What's one topic you could give an impromptu TED Talk on?",
    "If you could only keep five possessions, what would they be?",
    "How do you balance staying informed with avoiding information overload?",
    "What's a random fact you love sharing with people?",
    "What do you wish was taught more in schools?",
    "What’s one rule you live your life by?",
    "Do you think humans are fundamentally good or fundamentally flawed?",
    "If you could see into the future, would you choose to look?",
    "What's a challenge you initially hated but now appreciate?",
    "What small daily pleasure makes life worth living for you?",
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
    "Mindfulness – focusing on the present or self-awareness",
    "Creativity – exploring artistic or imaginative ideas",
    "Tech & AI – the impact of emerging technology",
    "Culture & Travel – experiences with places or traditions",
    "Health & Wellness – mental or physical wellbeing",
    "Food & Cooking – culinary experiences or recipes",
    "History – lessons from past events or figures",
    "Superpowers – imaginative abilities or heroics",
]

class PromptCog(commands.Cog):
    """Scheduled and on‑demand AI-powered prompt generator with type rotation and custom scheduler."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        size = getattr(cfg, 'PROMPT_HISTORY_SIZE', 5)
        self.history = deque(maxlen=size)
        # load recent type history and choose next index
        self.recent_types = self._load_state()
        self.rotation_index = 0
        self._choose_next_type()
        self._scheduler_task = None
        self._unused_fallback = list(FALLBACK_PROMPTS)
        random.shuffle(self._unused_fallback)

    def fetch_prompt(self) -> str:
        """Generate a new prompt via HF inference, including rotation and history."""
        prompt_type = PROMPT_TYPES[self.rotation_index]
        self.recent_types.append(self.rotation_index)
        self._save_state()
        self._choose_next_type()
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
                'max_tokens': int_env('HF_MAX_TOKENS', 50),
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
        if not self._unused_fallback:
            self._unused_fallback = list(FALLBACK_PROMPTS)
            random.shuffle(self._unused_fallback)
        prompt = self._unused_fallback.pop()
        self.history.append(prompt)
        return prompt

    def _load_state(self) -> deque:
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                return deque(data.get('recent_types', []), maxlen=RECENT_TYPE_COUNT)
            except Exception as exc:
                log.warning("Failed to load prompt state: %s", exc)
        return deque(maxlen=RECENT_TYPE_COUNT)

    def _save_state(self) -> None:
        try:
            STATE_FILE.write_text(json.dumps({'recent_types': list(self.recent_types)}))
        except Exception as exc:
            log.warning("Failed to save prompt state: %s", exc)

    def _choose_next_type(self) -> None:
        remaining = [i for i in range(len(PROMPT_TYPES)) if i not in self.recent_types]
        if not remaining:
            self.recent_types.clear()
            remaining = list(range(len(PROMPT_TYPES)))
        self.rotation_index = random.choice(remaining)

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
        log.info("skip_prompt invoked by %s in %s", ctx.author.id, chan_name(ctx.channel))
        prompt = self.fetch_prompt()
        await ctx.send(f"{prompt}")

async def setup(bot: commands.Bot):
    await bot.add_cog(PromptCog(bot))
