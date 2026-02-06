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

Self-tuning engagement system:
  • Exponential cooldown when prompts get low unique-user engagement
  • Data-driven category selection based on historical engagement
  • Poll-first recovery after cooldown for low-friction re-engagement
  • Day-of-week awareness to skip historically dead days

Configuration in bot_config.py:
  • DAILY_PING_CHANNEL: channel ID for daily‑ping (must be an integer)
  • DAILY_PROMPT_ENABLED: enable/disable the scheduler
  • PROMPT_SCHEDULE_HOUR: local hour to schedule daily prompts
  • PROMPT_SCHEDULE_MINUTE: local minute for prompt scheduling
  • PROMPT_POLL_RATIO: ratio of polls vs text prompts (0.0-1.0)
  • PROMPT_MIN_RESPONSES: minimum unique responders to avoid cooldown
  • PROMPT_MAX_COOLDOWN_DAYS: cap for exponential cooldown

Requires:
  • discord.py v2.4+ (for native Poll support)
  • PyYAML
"""
from __future__ import annotations
import random
import asyncio
import logging
from collections import defaultdict
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

# Minimum data points per category/DOW before trusting engagement stats
CATEGORY_MIN_SAMPLE_SIZE = 3

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
    Uses historical engagement data to select categories and skip low-engagement
    days. Backs off exponentially when prompts receive low engagement.
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

        # Last used info for recency penalty + archival
        self.last_category: str = ""
        self.last_prompt_type: str = ""  # "text" or "poll"

        # Poll-first recovery flag (set when cooldown expires)
        self._force_poll_after_cooldown: bool = False

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

    # ── Engagement data helpers ──────────────────────────────────────────

    async def _fetch_engagement_history(
        self,
        *,
        lookback_days: int = 90,
    ) -> list[dict]:
        """
        Fetch engagement stats for all prompts within the lookback window.

        Returns a list of dicts with keys:
            created_at, category, topic, day_of_week, unique_responders

        Uses a LATERAL join against discord.message + discord.user to compute
        unique non-bot responders for each prompt within 24 hours of posting.
        """
        if not self.pool:
            return []

        cutoff = datetime.now(LOCAL_TZ) - timedelta(days=lookback_days)

        try:
            rows = await self.pool.fetch(
                """
                SELECT
                    dp.created_at,
                    dp.category,
                    dp.topic,
                    EXTRACT(DOW FROM dp.created_at
                            AT TIME ZONE 'America/Los_Angeles')::int AS day_of_week,
                    COALESCE(eng.unique_responders, 0) AS unique_responders
                FROM discord.daily_prompt dp
                LEFT JOIN LATERAL (
                    SELECT COUNT(DISTINCT m.author_id) AS unique_responders
                    FROM discord.message m
                    JOIN discord."user" u ON u.user_id = m.author_id
                    WHERE m.channel_id = dp.thread_channel_id
                      AND m.created_at >= dp.created_at
                      AND m.created_at < dp.created_at + INTERVAL '24 hours'
                      AND u.is_bot = false
                ) eng ON true
                WHERE dp.created_at >= $1
                ORDER BY dp.created_at DESC
                """,
                cutoff,
            )
            return [dict(r) for r in rows]
        except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
            log.warning("Tables not available for engagement history query")
            return []

    # ── Cooldown logic ───────────────────────────────────────────────────

    async def _get_cooldown_info(self) -> tuple[bool, datetime | None, int]:
        """
        Calculate cooldown based on recent unique-user engagement.

        Returns:
            (should_skip, next_eligible_time, consecutive_low_engagement_count)

        Logic:
            - Fetch last 10 prompts with unique non-bot responder counts
            - Count consecutive prompts with unique_responders < MIN_RESPONSES
            - Cooldown = 2^(count-1) days, capped at MAX_COOLDOWN_DAYS
            - If last prompt was within cooldown period, skip
        """
        if not self.pool:
            return (False, None, 0)

        try:
            rows = await self.pool.fetch(
                """
                SELECT
                    dp.created_at,
                    COALESCE(eng.unique_responders, 0) AS unique_responders
                FROM discord.daily_prompt dp
                LEFT JOIN LATERAL (
                    SELECT COUNT(DISTINCT m.author_id) AS unique_responders
                    FROM discord.message m
                    JOIN discord."user" u ON u.user_id = m.author_id
                    WHERE m.channel_id = dp.thread_channel_id
                      AND m.created_at >= dp.created_at
                      AND m.created_at < dp.created_at + INTERVAL '24 hours'
                      AND u.is_bot = false
                ) eng ON true
                ORDER BY dp.created_at DESC
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
            if row["unique_responders"] < MIN_RESPONSES:
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

    # ── Category selection ───────────────────────────────────────────────

    async def _compute_category_weights(
        self,
        prompt_type: str,
    ) -> dict[str, float]:
        """
        Compute selection weights for prompt categories based on historical
        average unique responders.

        Categories with higher avg engagement get proportionally higher weight.
        Categories with < CATEGORY_MIN_SAMPLE_SIZE data points get a neutral
        weight (global average). The last-used category gets a 0.5× recency
        penalty to maintain variety.
        """
        templates = self.templates.get(
            "text_prompts" if prompt_type == "text" else "poll_prompts", {}
        )
        categories = list(templates.keys())
        if not categories:
            return {}

        # Default: equal weights
        equal_weight = 1.0 / len(categories)
        weights = {cat: equal_weight for cat in categories}

        history = await self._fetch_engagement_history(lookback_days=90)
        if not history:
            return weights

        # Filter to matching prompt type
        typed_history = [h for h in history if h.get("topic") == prompt_type]
        if not typed_history:
            return weights

        # Group by category
        category_engagement: dict[str, list[int]] = defaultdict(list)
        for entry in typed_history:
            cat = entry["category"]
            if cat in categories:  # Only count categories that still exist
                category_engagement[cat].append(entry["unique_responders"])

        # Compute weighted averages
        raw_weights: dict[str, float | None] = {}
        has_sufficient_data = False
        for cat in categories:
            samples = category_engagement.get(cat, [])
            if len(samples) >= CATEGORY_MIN_SAMPLE_SIZE:
                raw_weights[cat] = sum(samples) / len(samples)
                has_sufficient_data = True
            else:
                raw_weights[cat] = None  # Insufficient data

        if not has_sufficient_data:
            return weights

        # Fill insufficient-data categories with the global average
        all_avgs = [v for v in raw_weights.values() if v is not None]
        global_avg = sum(all_avgs) / len(all_avgs) if all_avgs else 1.0
        final_weights: dict[str, float] = {}
        for cat in categories:
            final_weights[cat] = raw_weights[cat] if raw_weights[cat] is not None else global_avg

        # Apply recency penalty: halve weight of last-used category
        if self.last_category in final_weights:
            final_weights[self.last_category] *= 0.5

        # Normalize so weights sum to 1.0
        total = sum(final_weights.values())
        if total > 0:
            weights = {cat: w / total for cat, w in final_weights.items()}

        return weights

    async def _select_text_prompt(self) -> tuple[str, str]:
        """
        Select a text prompt using data-driven category weights.
        Returns (prompt, category).
        """
        text_prompts = self.templates.get("text_prompts", {})
        if not text_prompts:
            return ("What's on your mind today?", "fallback")

        weights = await self._compute_category_weights("text")
        categories = list(text_prompts.keys())
        weight_list = [weights.get(cat, 1.0 / len(categories)) for cat in categories]

        category = random.choices(categories, weights=weight_list, k=1)[0]
        prompts = text_prompts[category]

        # Select a prompt not recently used
        available = [p for p in prompts if p not in self.past_prompts]
        if not available:
            # All prompts used, reset and allow repeats of older ones
            available = prompts

        prompt = random.choice(available)
        return (prompt, category)

    async def _select_poll(self) -> tuple[dict, str]:
        """
        Select a poll template using data-driven category weights.
        Returns (poll_dict, category).
        """
        poll_prompts = self.templates.get("poll_prompts", {})
        if not poll_prompts:
            return ({"question": "What's your preference?", "options": ["A", "B"]}, "fallback")

        weights = await self._compute_category_weights("poll")
        categories = list(poll_prompts.keys())
        weight_list = [weights.get(cat, 1.0 / len(categories)) for cat in categories]

        category = random.choices(categories, weights=weight_list, k=1)[0]
        polls = poll_prompts[category]

        # Select a poll not recently used (by question text)
        available = [p for p in polls if p.get("question", "") not in self.past_prompts]
        if not available:
            available = polls

        poll = random.choice(available)
        return (poll, category)

    def _should_use_poll(self) -> bool:
        """Determine if this prompt should be a poll based on POLL_RATIO."""
        return random.random() < POLL_RATIO

    # ── Day-of-week awareness ────────────────────────────────────────────

    async def _should_skip_day_of_week(self) -> bool:
        """
        Determine if today is a historically low-engagement day that should
        be skipped.

        Returns True if today's DOW has ≥ CATEGORY_MIN_SAMPLE_SIZE data points
        and average unique responders falls below MIN_RESPONSES.
        """
        history = await self._fetch_engagement_history(lookback_days=90)
        if not history:
            return False

        now = datetime.now(LOCAL_TZ)
        # Python weekday: Mon=0..Sun=6 ; PG DOW: Sun=0..Sat=6
        py_weekday = now.weekday()
        pg_dow = (py_weekday + 1) % 7

        day_entries = [h for h in history if h["day_of_week"] == pg_dow]

        if len(day_entries) < CATEGORY_MIN_SAMPLE_SIZE:
            log.debug(
                "DOW skip check: only %d data points for %s, not enough to skip",
                len(day_entries),
                now.strftime("%A"),
            )
            return False

        avg_engagement = sum(e["unique_responders"] for e in day_entries) / len(day_entries)

        if avg_engagement < MIN_RESPONSES:
            log.info(
                "Skipping %s: avg engagement %.1f < threshold %d "
                "(based on %d historical prompts)",
                now.strftime("%A"),
                avg_engagement,
                MIN_RESPONSES,
                len(day_entries),
            )
            return True

        return False

    # ── Prompt archival ──────────────────────────────────────────────────

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

    # ── Sending prompts ──────────────────────────────────────────────────

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

        # Poll-first recovery: after cooldown, send a poll for low-friction re-engagement
        if self._force_poll_after_cooldown:
            self._force_poll_after_cooldown = False
            log.info("Sending poll (post-cooldown recovery)")
            await self._send_poll(channel)
        elif self._should_use_poll():
            await self._send_poll(channel)
        else:
            await self._send_text_prompt(channel)

    async def _send_text_prompt(self, channel: discord.TextChannel):
        """Send a text-based prompt."""
        prompt, category = await self._select_text_prompt()

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
        poll_data, category = await self._select_poll()

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

    # ── Scheduling ───────────────────────────────────────────────────────

    def _next_run_time(self, now: datetime) -> datetime:
        """Calculate the next scheduled run time."""
        next_run = now.replace(
            hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE, second=0, microsecond=0
        )
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run

    async def _scheduler(self):
        """Main scheduling loop with cooldown, DOW skipping, and poll recovery."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            now = datetime.now(LOCAL_TZ)
            next_run = self._next_run_time(now)

            # ── Step 1: Check cooldown ──
            should_skip, cooldown_until, low_count = await self._get_cooldown_info()

            if should_skip and cooldown_until:
                # In cooldown — sleep until cooldown expires at scheduled time
                cooldown_date = cooldown_until.astimezone(LOCAL_TZ).date()
                next_check = datetime(
                    cooldown_date.year,
                    cooldown_date.month,
                    cooldown_date.day,
                    SCHEDULE_HOUR,
                    SCHEDULE_MINUTE,
                    tzinfo=LOCAL_TZ,
                )
                if next_check <= now:
                    next_check += timedelta(days=1)

                formatted = next_check.strftime("%I:%M:%S %p %Z on %b %d").lstrip('0')
                log.info(
                    "Cooldown active (%d low-engagement prompts). Next check at %s",
                    low_count,
                    formatted,
                )
                wait_seconds = (next_check - now).total_seconds()
                await asyncio.sleep(wait_seconds)
                continue  # Re-check on wake

            # ── Step 2: Set poll-recovery flag if cooldown just expired ──
            if low_count > 0:
                self._force_poll_after_cooldown = True
                log.info("Post-cooldown recovery: will force poll for re-engagement")

            # ── Step 3: Sleep until scheduled time ──
            formatted = next_run.strftime("%I:%M:%S %p %Z").lstrip('0')
            log.info("Next prompt scheduled at %s", formatted)
            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            # ── Step 4: Re-check cooldown right before sending ──
            should_skip, _, _ = await self._get_cooldown_info()
            if should_skip:
                log.info("Cooldown triggered just before send, skipping this cycle")
                continue

            # ── Step 5: Check DOW skipping ──
            if await self._should_skip_day_of_week():
                log.info("Skipping prompt: today is a historically low-engagement day")
                continue  # No prompt = no low engagement data = no cooldown impact

            # ── Step 6: Fire the prompt ──
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

    # ── Commands ─────────────────────────────────────────────────────────

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
            prompt, category = await self._select_text_prompt()
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
        """Show prompt system statistics including engagement analytics."""
        text_prompts = self.templates.get("text_prompts", {})
        poll_prompts = self.templates.get("poll_prompts", {})

        text_count = sum(len(v) for v in text_prompts.values())
        poll_count = sum(len(v) for v in poll_prompts.values())

        # Cooldown status
        should_skip, cooldown_until, low_count = await self._get_cooldown_info()
        if should_skip and cooldown_until:
            cooldown_str = cooldown_until.astimezone(LOCAL_TZ).strftime("%b %d at %I:%M %p")
            cooldown_status = f"⏸️ Paused until {cooldown_str} ({low_count} low-engagement prompts)"
        elif low_count > 0:
            cooldown_status = f"✅ Ready (cooldown expired, was {low_count} low-engagement)"
        else:
            cooldown_status = "✅ Active (good engagement)"

        # Category weights (top 3 for each type)
        text_weights = await self._compute_category_weights("text")
        poll_weights = await self._compute_category_weights("poll")
        top_text = sorted(text_weights.items(), key=lambda x: x[1], reverse=True)[:3]
        top_poll = sorted(poll_weights.items(), key=lambda x: x[1], reverse=True)[:3]
        text_weight_str = ", ".join(f"{cat} ({w:.0%})" for cat, w in top_text) or "n/a"
        poll_weight_str = ", ".join(f"{cat} ({w:.0%})" for cat, w in top_poll) or "n/a"

        # DOW analysis
        history = await self._fetch_engagement_history(lookback_days=90)
        dow_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        dow_entries: dict[int, list[int]] = defaultdict(list)
        for entry in history:
            dow_entries[entry["day_of_week"]].append(entry["unique_responders"])

        skip_days = []
        dow_lines = []
        for dow in range(7):
            samples = dow_entries.get(dow, [])
            if len(samples) >= CATEGORY_MIN_SAMPLE_SIZE:
                avg = sum(samples) / len(samples)
                status = "⏭️" if avg < MIN_RESPONSES else "✅"
                dow_lines.append(f"  {dow_names[dow]}: {status} {avg:.1f} avg ({len(samples)})")
                if avg < MIN_RESPONSES:
                    skip_days.append(dow_names[dow])
            else:
                dow_lines.append(f"  {dow_names[dow]}: 📊 {len(samples)} prompts (need {CATEGORY_MIN_SAMPLE_SIZE})")

        skip_str = ", ".join(skip_days) if skip_days else "none"

        # Recovery status
        recovery_str = "Yes (next prompt will be a poll)" if self._force_poll_after_cooldown else "No"

        stats = (
            f"**Prompt System Stats**\n"
            f"• Text prompts: {text_count} across {len(text_prompts)} categories\n"
            f"• Poll templates: {poll_count} across {len(poll_prompts)} categories\n"
            f"• Poll ratio: {POLL_RATIO:.0%}\n"
            f"• Schedule: {SCHEDULE_HOUR}:{SCHEDULE_MINUTE:02d} PT\n"
            f"• Used prompts in history: {len(self.past_prompts)}\n"
            f"• Scheduler enabled: {self.prompts_enabled}\n"
            f"• Engagement threshold: {MIN_RESPONSES} unique responders\n"
            f"• Cooldown status: {cooldown_status}\n"
            f"• Poll recovery pending: {recovery_str}\n"
            f"• Top text categories: {text_weight_str}\n"
            f"• Top poll categories: {poll_weight_str}\n"
            f"• Days skipped: {skip_str}\n"
            f"**Day-of-week engagement:**\n" + "\n".join(dow_lines)
        )
        await ctx.send(stats)


async def setup(bot: commands.Bot):
    await bot.add_cog(PromptCog(bot))
