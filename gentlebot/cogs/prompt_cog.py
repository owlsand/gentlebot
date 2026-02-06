"""
prompt_cog.py – Template-Based Daily Prompt Generator for Gentlebot
====================================================================
Posts human-curated prompts and native Discord polls to drive engagement.
No LLM generation - just template selection and rotation.

Key principles:
  - Human voice > LLM voice
  - Specific > Vague
  - Low barrier to entry
  - Mix of text prompts and native polls

Configuration in bot_config.py:
  • DAILY_PING_CHANNEL: channel ID for daily‑ping (must be an integer)
  • DAILY_PROMPT_ENABLED: enable/disable the scheduler
  • PROMPT_SCHEDULE_HOUR: local hour to schedule daily prompts
  • PROMPT_SCHEDULE_MINUTE: local minute for prompt scheduling
  • PROMPT_POLL_RATIO: ratio of polls vs text prompts (0.0-1.0)

Requires:
  • discord.py v2.4+ (for native Poll support)
  • PyYAML
"""
from __future__ import annotations
import random
import asyncio
import logging
from datetime import datetime, timedelta
from collections import deque
from pathlib import Path
import discord
from discord.ext import commands
from ..util import chan_name, user_name
from ..db import get_pool
from .. import bot_config as cfg
from zoneinfo import ZoneInfo
import asyncpg
import yaml

log = logging.getLogger(f"gentlebot.{__name__}")

# Timezone for scheduling
LOCAL_TZ = ZoneInfo("America/Los_Angeles")
SCHEDULE_HOUR = getattr(cfg, 'PROMPT_SCHEDULE_HOUR', 12)
SCHEDULE_MINUTE = getattr(cfg, 'PROMPT_SCHEDULE_MINUTE', 30)
POLL_RATIO = getattr(cfg, 'PROMPT_POLL_RATIO', 0.4)

# Engagement-based cooldown settings
MIN_RESPONSES = getattr(cfg, 'PROMPT_MIN_RESPONSES', 2)
MAX_COOLDOWN_DAYS = getattr(cfg, 'PROMPT_MAX_COOLDOWN_DAYS', 7)

# Poll duration (24 hours)
POLL_DURATION = timedelta(hours=24)

# Path to templates file
TEMPLATES_PATH = Path(__file__).parent.parent / "data" / "prompt_templates.yaml"


def load_templates() -> dict:
    """Load prompt templates from YAML file."""
    try:
        with open(TEMPLATES_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        log.error("Template file not found: %s", TEMPLATES_PATH)
        return {}
    except yaml.YAMLError as e:
        log.error("Failed to parse template file: %s", e)
        return {}


class PromptCog(commands.Cog):
    """
    Template-based prompt generator with native Discord poll support.

    Posts a mix of text prompts and interactive polls based on PROMPT_POLL_RATIO.
    Tracks engagement and rotates through categories to maintain variety.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.history: deque[str] = deque(maxlen=20)  # Track recent prompts to avoid repeats
        self._scheduler_task = None
        self.pool: asyncpg.Pool | None = None
        self.past_prompts: set[str] = set()
        self.prompts_enabled = getattr(cfg, "DAILY_PROMPT_ENABLED", False)

        # Load templates
        self.templates = load_templates()

        # Track category usage for weighted rotation
        self.text_category_weights: dict[str, float] = {}
        self.poll_category_weights: dict[str, float] = {}
        self._init_category_weights()

        # Last used info for archival
        self.last_category: str = ""
        self.last_prompt_type: str = ""  # "text" or "poll"

    def _init_category_weights(self):
        """Initialize category weights for weighted random selection."""
        text_prompts = self.templates.get("text_prompts", {})
        poll_prompts = self.templates.get("poll_prompts", {})

        # Equal weights initially - categories used recently get lower weights
        for cat in text_prompts:
            self.text_category_weights[cat] = 1.0
        for cat in poll_prompts:
            self.poll_category_weights[cat] = 1.0

    async def cog_load(self) -> None:
        """Load past prompts from database to avoid repetition."""
        try:
            self.pool = await get_pool()
        except RuntimeError:
            return
        try:
            rows = await self.pool.fetch(
                "SELECT prompt FROM discord.daily_prompt ORDER BY created_at"
            )
        except asyncpg.UndefinedTableError:
            log.warning("daily_prompt table not found; prompt history disabled")
            return
        self.past_prompts = {r["prompt"] for r in rows}
        for p in [r["prompt"] for r in rows[-self.history.maxlen:]]:
            self.history.append(p)

    async def cog_unload(self) -> None:
        if self._scheduler_task:
            self._scheduler_task.cancel()
            self._scheduler_task = None
        self.pool = None

    def _select_text_prompt(self) -> tuple[str, str]:
        """
        Select a text prompt using weighted random category selection.
        Returns (prompt, category).
        """
        text_prompts = self.templates.get("text_prompts", {})
        if not text_prompts:
            return ("What's on your mind today?", "fallback")

        # Weighted random selection of category
        categories = list(text_prompts.keys())
        weights = [self.text_category_weights.get(cat, 1.0) for cat in categories]

        # Normalize weights
        total = sum(weights)
        if total > 0:
            weights = [w / total for w in weights]
        else:
            weights = [1.0 / len(categories)] * len(categories)

        category = random.choices(categories, weights=weights, k=1)[0]
        prompts = text_prompts[category]

        # Select a prompt not recently used
        available = [p for p in prompts if p not in self.past_prompts]
        if not available:
            # All prompts used, reset and allow repeats of older ones
            available = prompts

        prompt = random.choice(available)

        # Decrease weight of used category (will recover over time)
        self.text_category_weights[category] *= 0.5

        # Slowly restore other category weights
        for cat in self.text_category_weights:
            if cat != category:
                self.text_category_weights[cat] = min(1.0, self.text_category_weights[cat] * 1.1)

        return (prompt, category)

    def _select_poll(self) -> tuple[dict, str]:
        """
        Select a poll template using weighted random category selection.
        Returns (poll_dict, category).
        """
        poll_prompts = self.templates.get("poll_prompts", {})
        if not poll_prompts:
            return ({"question": "What's your preference?", "options": ["A", "B"]}, "fallback")

        # Weighted random selection of category
        categories = list(poll_prompts.keys())
        weights = [self.poll_category_weights.get(cat, 1.0) for cat in categories]

        # Normalize weights
        total = sum(weights)
        if total > 0:
            weights = [w / total for w in weights]
        else:
            weights = [1.0 / len(categories)] * len(categories)

        category = random.choices(categories, weights=weights, k=1)[0]
        polls = poll_prompts[category]

        # Select a poll not recently used (by question text)
        available = [p for p in polls if p.get("question", "") not in self.past_prompts]
        if not available:
            available = polls

        poll = random.choice(available)

        # Decrease weight of used category
        self.poll_category_weights[category] *= 0.5

        # Slowly restore other category weights
        for cat in self.poll_category_weights:
            if cat != category:
                self.poll_category_weights[cat] = min(1.0, self.poll_category_weights[cat] * 1.1)

        return (poll, category)

    def _should_use_poll(self) -> bool:
        """Determine if this prompt should be a poll based on POLL_RATIO."""
        return random.random() < POLL_RATIO

    async def _get_cooldown_info(self) -> tuple[bool, datetime | None, int]:
        """
        Calculate cooldown based on recent engagement history.

        Returns:
            (should_skip, next_eligible_time, consecutive_low_engagement_count)

        Logic:
            - Query recent prompts ordered by date (most recent first)
            - Count consecutive prompts with message_count < MIN_RESPONSES
            - Cooldown = 2^(count-1) days, capped at MAX_COOLDOWN_DAYS
            - If last prompt was within cooldown period, skip
        """
        if not self.pool:
            return (False, None, 0)

        try:
            # Get last 10 prompts to analyze engagement pattern
            rows = await self.pool.fetch(
                """
                SELECT created_at, message_count
                FROM discord.daily_prompt
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
        except asyncpg.UndefinedTableError:
            return (False, None, 0)

        if not rows:
            return (False, None, 0)

        # Count consecutive low-engagement prompts from the most recent
        consecutive_low = 0
        for row in rows:
            if row["message_count"] < MIN_RESPONSES:
                consecutive_low += 1
            else:
                break  # Good engagement breaks the streak

        if consecutive_low == 0:
            # Last prompt had good engagement, no cooldown needed
            return (False, None, 0)

        # Calculate required cooldown: 2^(n-1) days, capped at max
        # n=1 → 1 day, n=2 → 2 days, n=3 → 4 days, n=4 → 8 days...
        cooldown_days = min(2 ** (consecutive_low - 1), MAX_COOLDOWN_DAYS)

        # Check if enough time has passed since last prompt
        last_prompt_time = rows[0]["created_at"]
        # Make last_prompt_time timezone-aware if it isn't
        if last_prompt_time.tzinfo is None:
            from zoneinfo import ZoneInfo
            last_prompt_time = last_prompt_time.replace(tzinfo=ZoneInfo("UTC"))

        next_eligible = last_prompt_time + timedelta(days=cooldown_days)
        now = datetime.now(LOCAL_TZ)

        if now < next_eligible:
            # Still in cooldown period
            log.info(
                "Cooldown active: %d consecutive low-engagement prompts, "
                "waiting until %s (%d day cooldown)",
                consecutive_low,
                next_eligible.strftime("%Y-%m-%d %I:%M %p %Z"),
                cooldown_days,
            )
            return (True, next_eligible, consecutive_low)

        # Cooldown period has passed
        log.info(
            "Cooldown expired: was %d days for %d consecutive low-engagement prompts",
            cooldown_days,
            consecutive_low,
        )
        return (False, None, consecutive_low)

    async def _archive_prompt(
        self, prompt: str, category: str, channel_id: int, prompt_type: str
    ) -> None:
        """Store prompt in database for history tracking."""
        if not self.pool:
            return
        try:
            # Use topic field to store prompt type (text/poll)
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
                channel_id,
                prompt_type,
            )
        except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
            log.warning("daily_prompt table not found; prompt not archived")

    async def _send_prompt(self):
        """Generate and send the daily prompt (text or poll)."""
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
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception as exc:
                log.error("Unable to find channel with ID %s: %s", channel_id, exc)
                return

        # Decide: poll or text?
        if self._should_use_poll():
            await self._send_poll(channel)
        else:
            await self._send_text_prompt(channel)

    async def _send_text_prompt(self, channel: discord.TextChannel):
        """Send a text-based prompt."""
        prompt, category = self._select_text_prompt()

        self.last_category = category
        self.last_prompt_type = "text"

        try:
            await channel.send(prompt)
            log.info("Sent text prompt [%s]: %s", category, prompt[:50])
        except Exception as exc:
            log.error("Failed to send text prompt: %s", exc)
            return

        # Track history
        self.history.append(prompt)
        self.past_prompts.add(prompt)

        # Archive
        await self._archive_prompt(prompt, category, channel.id, "text")

    async def _send_poll(self, channel: discord.TextChannel):
        """Send a native Discord poll."""
        poll_data, category = self._select_poll()

        question = poll_data.get("question", "What do you think?")
        options = poll_data.get("options", ["Option A", "Option B"])

        self.last_category = category
        self.last_prompt_type = "poll"

        try:
            # Create native Discord poll
            poll = discord.Poll(
                question=discord.PollQuestion(text=question),
                duration=POLL_DURATION,
            )

            # Add answers
            for option in options[:10]:  # Discord limits to 10 options
                poll.add_answer(text=option)

            await channel.send(poll=poll)
            log.info("Sent poll [%s]: %s", category, question)
        except Exception as exc:
            log.error("Failed to send poll: %s", exc)
            # Fallback to text prompt if poll fails
            await self._send_text_prompt(channel)
            return

        # Track history using question as identifier
        self.history.append(question)
        self.past_prompts.add(question)

        # Archive
        await self._archive_prompt(question, category, channel.id, "poll")

    def _next_run_time(self, now: datetime) -> datetime:
        """Calculate the next scheduled run time."""
        next_run = now.replace(
            hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE, second=0, microsecond=0
        )
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run

    async def _scheduler(self):
        """Main scheduling loop for daily prompts with engagement-based cooldown."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            now = datetime.now(LOCAL_TZ)
            next_run = self._next_run_time(now)

            # Check if we're in a cooldown period due to low engagement
            should_skip, cooldown_until, low_count = await self._get_cooldown_info()

            if should_skip and cooldown_until:
                # In cooldown - calculate when we should next check
                # Wake up at the scheduled time on the day cooldown expires
                cooldown_date = cooldown_until.astimezone(LOCAL_TZ).date()
                next_check = datetime(
                    cooldown_date.year,
                    cooldown_date.month,
                    cooldown_date.day,
                    SCHEDULE_HOUR,
                    SCHEDULE_MINUTE,
                    tzinfo=LOCAL_TZ,
                )
                # If that time already passed today, move to next day
                if next_check <= now:
                    next_check += timedelta(days=1)

                formatted = next_check.strftime("%I:%M:%S %p %Z on %b %d").lstrip('0')
                log.info(
                    "Cooldown active (%d low-engagement prompts). "
                    "Next check at %s",
                    low_count,
                    formatted,
                )
                wait_seconds = (next_check - now).total_seconds()
                await asyncio.sleep(wait_seconds)
                continue  # Re-check cooldown after waking

            # No cooldown - schedule normally
            formatted = next_run.strftime("%I:%M:%S %p %Z").lstrip('0')
            log.info("Next prompt scheduled at %s", formatted)

            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            # Re-check cooldown right before sending (engagement might have been updated)
            should_skip, _, _ = await self._get_cooldown_info()
            if should_skip:
                log.info("Cooldown triggered just before send, skipping this cycle")
                continue

            log.info(
                "Firing scheduled prompt at %s",
                datetime.now(LOCAL_TZ).strftime("%I:%M:%S %p %Z"),
            )
            try:
                await self._send_prompt()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Scheduled prompt failed")

    @commands.Cog.listener()
    async def on_ready(self):
        """Start or stop the scheduler based on configuration."""
        if not self.prompts_enabled:
            if self._scheduler_task and not self._scheduler_task.done():
                self._scheduler_task.cancel()
                try:
                    await self._scheduler_task
                except asyncio.CancelledError:
                    pass
            self._scheduler_task = None
            log.info("Daily prompt scheduler paused by configuration.")
            return

        if self._scheduler_task is None or self._scheduler_task.done():
            log.info("Starting prompt scheduler task.")
            self._scheduler_task = self.bot.loop.create_task(self._scheduler())

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message) -> None:
        """Track message count for engagement metrics."""
        if msg.author.bot or not self.pool:
            return
        try:
            today = datetime.now(tz=LOCAL_TZ).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).astimezone(ZoneInfo("UTC"))
            tomorrow = today + timedelta(days=1)
            await self.pool.execute(
                """
                UPDATE discord.daily_prompt
                   SET message_count = message_count + 1
                 WHERE thread_channel_id=$1
                   AND created_at >= $2
                   AND created_at < $3
                """,
                msg.channel.id,
                today,
                tomorrow,
            )
        except asyncpg.UndefinedTableError:
            pass

    @commands.command(name='skip_prompt')
    async def skip_prompt(self, ctx: commands.Context):
        """Immediately generate and post a new prompt."""
        log.info(
            "skip_prompt invoked by %s in %s",
            user_name(ctx.author),
            chan_name(ctx.channel),
        )

        # Decide: poll or text?
        if self._should_use_poll():
            await self._send_poll(ctx.channel)
        else:
            prompt, category = self._select_text_prompt()
            self.history.append(prompt)
            self.past_prompts.add(prompt)
            await ctx.send(prompt)

    @commands.command(name='prompt_poll')
    async def prompt_poll(self, ctx: commands.Context):
        """Force a poll prompt (for testing)."""
        log.info(
            "prompt_poll invoked by %s in %s",
            user_name(ctx.author),
            chan_name(ctx.channel),
        )
        await self._send_poll(ctx.channel)

    @commands.command(name='prompt_text')
    async def prompt_text(self, ctx: commands.Context):
        """Force a text prompt (for testing)."""
        log.info(
            "prompt_text invoked by %s in %s",
            user_name(ctx.author),
            chan_name(ctx.channel),
        )
        await self._send_text_prompt(ctx.channel)

    @commands.command(name='prompt_stats')
    async def prompt_stats(self, ctx: commands.Context):
        """Show prompt system statistics including cooldown status."""
        text_prompts = self.templates.get("text_prompts", {})
        poll_prompts = self.templates.get("poll_prompts", {})

        text_count = sum(len(v) for v in text_prompts.values())
        poll_count = sum(len(v) for v in poll_prompts.values())

        # Check cooldown status
        should_skip, cooldown_until, low_count = await self._get_cooldown_info()
        if should_skip and cooldown_until:
            cooldown_str = cooldown_until.astimezone(LOCAL_TZ).strftime("%b %d at %I:%M %p")
            cooldown_status = f"⏸️ Paused until {cooldown_str} ({low_count} low-engagement prompts)"
        elif low_count > 0:
            cooldown_status = f"✅ Ready (cooldown expired, was {low_count} low-engagement)"
        else:
            cooldown_status = "✅ Active (good engagement)"

        stats = (
            f"**Prompt System Stats**\n"
            f"• Text prompts: {text_count} across {len(text_prompts)} categories\n"
            f"• Poll templates: {poll_count} across {len(poll_prompts)} categories\n"
            f"• Poll ratio: {POLL_RATIO:.0%}\n"
            f"• Schedule: {SCHEDULE_HOUR}:{SCHEDULE_MINUTE:02d} PT\n"
            f"• Used prompts in history: {len(self.past_prompts)}\n"
            f"• Scheduler enabled: {self.prompts_enabled}\n"
            f"• Engagement threshold: {MIN_RESPONSES} responses\n"
            f"• Cooldown status: {cooldown_status}"
        )
        await ctx.send(stats)


async def setup(bot: commands.Bot):
    await bot.add_cog(PromptCog(bot))
