"""
prompt_cog.py – Dynamic Daily‑Ping Prompt Generator for Gentlebot
================================================================
Generates a rotating, AI-powered prompt each day via Gemini inference,
posts to DAILY_PING on schedule, and provides a command to skip to a new prompt.

Configuration in bot_config.py:
  • DAILY_PING_CHANNEL: channel ID for daily‑ping (must be an integer)
  • PROMPT_SCHEDULE_HOUR: (optional) local hour to schedule daily prompts
  • PROMPT_SCHEDULE_MINUTE: (optional) local minute for prompt scheduling
  • PROMPT_HISTORY_SIZE: how many past prompts to send as context

Requires:
  • discord.py v2+
  • requests
  • zoneinfo (stdlib) or backports.zoneinfo
"""
from __future__ import annotations
import random
import asyncio
import logging
from datetime import datetime, timedelta
from collections import deque
import discord
from discord.ext import commands
from ..util import chan_name, user_name
from ..db import get_pool
from .. import bot_config as cfg
from ..llm.router import router, SafetyBlocked
from ..infra.quotas import RateLimited
from zoneinfo import ZoneInfo
import asyncpg
import requests

# Use a hierarchical logger so messages propagate to the main gentlebot logger
log = logging.getLogger(f"gentlebot.{__name__}")

# Timezone for scheduling
LOCAL_TZ = ZoneInfo("America/Los_Angeles")
SCHEDULE_HOUR = getattr(cfg, 'PROMPT_SCHEDULE_HOUR', 12)
SCHEDULE_MINUTE = getattr(cfg, 'PROMPT_SCHEDULE_MINUTE', 30)

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
    "Which app do you check first every morning and why?",
    "How do you manage your online privacy on a daily basis?",
    "What's one piece of digital clutter you'd love to eliminate?",
]


def _strip_outer_quotes(text: str) -> str:
    """Remove matching leading and trailing single or double quotes."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return text

# Prompt categories
PROMPT_CATEGORIES = [
    "Recent Server Discussion",
    "Engagement Bait",
    "Sports News",
]

SPORTS_NEWS_PATHS = [
    "soccer/eng.1",
    "racing/f1",
    "football/nfl"
]

class PromptCog(commands.Cog):
    """Scheduled and on‑demand AI-powered prompt generator with random category selection."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        size = getattr(cfg, 'PROMPT_HISTORY_SIZE', 5)
        self.history = deque(maxlen=size)
        self._scheduler_task = None
        self.pool: asyncpg.Pool | None = None
        self.past_prompts: set[str] = set()
        self.last_category: str = ""
        self.last_topic: str | None = None

    async def cog_load(self) -> None:
        try:
            self.pool = await get_pool()
        except RuntimeError:
            return
        try:
            rows = await self.pool.fetch(
                "SELECT prompt FROM discord.daily_prompt ORDER BY created_at"
            )
        except asyncpg.UndefinedTableError:  # pragma: no cover - requires DB
            log.warning("daily_prompt table not found; prompt history disabled")
            return
        self.past_prompts = {r["prompt"] for r in rows}
        for p in [r["prompt"] for r in rows[-self.history.maxlen:]]:
            self.history.append(p)

    async def cog_unload(self) -> None:
        self.pool = None

    async def fetch_prompt(self) -> str:
        """Generate a new prompt via Gemini inference, including history."""
        category = random.choice(PROMPT_CATEGORIES)
        self.last_category = category
        messages = [
            {
                'role': 'system',
                'content': (
                    'You generate creative discussion prompts for a friendly Discord group.'
                ),
            }
        ]
        messages += [{'role': 'assistant', 'content': p} for p in self.history]
        topic = None
        if category == "Recent Server Discussion":
            topic = await self._recent_server_topic()
            user_content = (
                f"Generate one concise prompt about the topic '{topic}'. "
                "It should be a question, assertion, or novel insight. "
                "Respond only with the prompt itself and nothing else."
            )
        elif category == "Sports News":
            topic = await self._sports_news_topic()
            if topic:
                user_content = (
                    f"Generate one concise prompt about the sports news headline '{topic}'. "
                    "It should be a question, assertion, or novel insight. "
                    "Respond only with the prompt itself and nothing else."
                )
            else:
                user_content = (
                    "Generate one short prompt related to recent sports news. "
                    "Respond only with the prompt itself and nothing else."
                )
        else:  # Engagement Bait
            user_content = (
                "Generate one short engagement bait prompt designed to solicit reactions or responses. "
                "Respond only with the prompt itself and nothing else."
            )
        messages.append({'role': 'user', 'content': user_content})
        try:
            content = await asyncio.to_thread(
                router.generate, "scheduled", messages, 0.8
            )
            if content:
                prompt = _strip_outer_quotes(content)
                if prompt not in self.past_prompts:
                    self.history.append(prompt)
                    self.past_prompts.add(prompt)
                    self.last_topic = topic
                    return prompt
        except (RateLimited, SafetyBlocked) as e:
            log.warning("scheduled prompt generation failed: %s", e)
        except Exception as e:  # pragma: no cover - network
            log.exception("inference error: %s", e)
        prompt = random.choice(FALLBACK_PROMPTS) if FALLBACK_PROMPTS else "Share something interesting today."
        prompt = _strip_outer_quotes(prompt)
        self.history.append(prompt)
        self.past_prompts.add(prompt)
        self.last_topic = topic
        return prompt

    async def _archive_prompt(
        self, prompt: str, category: str, thread_id: int, topic: str | None = None
    ) -> None:
        if not self.pool:
            return
        try:
            await self.pool.execute(
                """
                INSERT INTO discord.daily_prompt
                    (prompt, category, thread_channel_id, message_count, topic)
                VALUES ($1, $2, $3, 0, $4)
                ON CONFLICT (prompt) DO UPDATE SET
                    category = EXCLUDED.category,
                    thread_channel_id = EXCLUDED.thread_channel_id,
                    message_count = 0,
                    topic = EXCLUDED.topic,
                    created_at = NOW()
                """,
                prompt,
                category,
                thread_id,
                topic,
            )
        except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):  # pragma: no cover - requires DB
            log.warning("daily_prompt table not found; prompt not archived")

    async def _recent_server_topic(self) -> str:
        if not self.pool:
            return "the community"
        rows = await self.pool.fetch(
            """
            SELECT m.content
            FROM message m
            JOIN "user" u ON u.user_id = m.author_id
            JOIN channel c ON c.channel_id = m.channel_id
            WHERE u.is_bot = FALSE
              AND c.type = 0
              AND m.created_at >= now() - interval '72 hours'
            ORDER BY m.created_at DESC
            LIMIT 200
            """,
        )
        text = "\n".join(r["content"] for r in rows if r["content"])
        if not text:
            return "the community"
        try:
            content = await asyncio.to_thread(
                router.generate,
                "scheduled",
                [{'role': 'user', 'content': 'Summarize the main topic of these messages in a short noun phrase.\n' + text}],
                0.8,
            )
            return content.strip() or "the community"
        except RateLimited:
            return "the community"
        except SafetyBlocked:
            return "the community"
        except Exception as exc:  # pragma: no cover - network
            log.exception("topic summary failed: %s", exc)
            return "the community"

    async def _sports_news_topic(self) -> str | None:
        """Fetch a random headline from ESPN's general sports news feed."""
        path = random.choice(SPORTS_NEWS_PATHS)
        try:
            resp = await asyncio.to_thread(
                requests.get,
                f"https://site.api.espn.com/apis/site/v2/sports/{path}/news",
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            headlines = [
                a.get("headline") for a in data.get("articles", []) if a.get("headline")
            ]
            return random.choice(headlines) if headlines else None
        except Exception as exc:  # pragma: no cover - network
            log.exception("sports news fetch failed: %s", exc)
            return None

    def _next_run_time(self, now: datetime) -> datetime:
        next_run = now.replace(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run

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
        prompt = await self.fetch_prompt()
        category = self.last_category
        try:
            msg = await channel.send(f"{prompt}")
        except Exception as exc:
            log.error("Failed to send prompt message: %s", exc)
            return
        await self._archive_prompt(prompt, category, msg.id, self.last_topic)

    async def _scheduler(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            now = datetime.now(LOCAL_TZ)
            next_run = self._next_run_time(now)
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

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message) -> None:
        if msg.author.bot or not self.pool:
            return
        try:
            row = await self.pool.fetchrow(
                "SELECT 1 FROM discord.daily_prompt WHERE thread_channel_id=$1",
                msg.channel.id,
            )
            if row:
                await self.pool.execute(
                    "UPDATE discord.daily_prompt SET message_count = message_count + 1 WHERE thread_channel_id=$1",
                    msg.channel.id,
                )
        except asyncpg.UndefinedTableError:  # pragma: no cover - requires DB
            pass

    @commands.command(name='skip_prompt')
    async def skip_prompt(self, ctx: commands.Context):
        log.info("skip_prompt invoked by %s in %s", user_name(ctx.author), chan_name(ctx.channel))
        prompt = await self.fetch_prompt()
        await ctx.send(f"{prompt}")

async def setup(bot: commands.Bot):
    await bot.add_cog(PromptCog(bot))
