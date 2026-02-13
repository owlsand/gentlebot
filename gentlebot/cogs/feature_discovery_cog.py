"""
feature_discovery_cog.py – Contextual Tips & Feature Spotlight
==============================================================
Helps users discover unused bot features via two mechanisms:

1. **Contextual tips** (on_message listener):
   Detects message patterns that match an existing feature and replies
   with a one-time, friendly hint.  Each tip is shown at most once per
   user, with a global rate-limit of one tip per channel per 24 hours.

2. **Periodic feature spotlight** (scheduled task):
   Posts a "Feature Spotlight" embed highlighting an underused feature
   every N days (configurable via FEATURE_SPOTLIGHT_INTERVAL_DAYS).

Configuration in bot_config.py:
  • FEATURE_DISCOVERY_ENABLED: Master toggle (default: True)
  • FEATURE_SPOTLIGHT_INTERVAL_DAYS: Days between spotlights (default: 5)
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from urllib.parse import urlparse

import discord
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from discord.ext import commands

from .. import bot_config as cfg
from ..capabilities import (
    CogCapabilities,
    ScheduledCapability,
    Category,
)
from ..infra import PoolAwareCog, require_pool, idempotent_task, daily_key

log = logging.getLogger(f"gentlebot.{__name__}")

LA = pytz.timezone("America/Los_Angeles")

# ---------------------------------------------------------------------------
# Tip definitions
# ---------------------------------------------------------------------------

# URL regex (reused from link_summarizer_cog)
URL_PATTERN = re.compile(r'https?://[^\s<>"\')\]]+', re.IGNORECASE)

# Domains to skip (image/GIF hosts that aren't summarizable)
_SKIP_DOMAINS = {
    "tenor.com", "giphy.com", "imgur.com", "gfycat.com", "klipy.com",
    "media.discordapp.net", "cdn.discordapp.com",
    "i.redd.it", "v.redd.it", "preview.redd.it",
    "i.imgur.com", "media.tenor.com", "c.tenor.com",
}

# File extensions to skip (media files that aren't summarizable)
_SKIP_EXTENSIONS = frozenset({
    ".gif", ".gifv", ".jpg", ".jpeg", ".png", ".webp",
    ".mp4", ".mov", ".webm", ".svg", ".bmp", ".ico",
    ".mp3", ".wav", ".ogg", ".avif",
})

# Pattern to detect "how active" / "who's posting" style questions
ACTIVITY_PATTERN = re.compile(
    r"\b(how active|who'?s posting|server stats|activity report)\b",
    re.IGNORECASE,
)

# Minimum message length for TL;DR tip
LONG_MESSAGE_THRESHOLD = 500

# Each entry: (tip_key, detect_func, tip_message)
# detect_func(message) -> bool
TIP_DEFINITIONS: list[tuple[str, str]] = [
    (
        "tldr",
        "btw — I added a 📝 to that message. Tap it to get a quick TL;DR!",
    ),
    (
        "link_summary",
        "btw — I added a 📋 to that link. Tap it to get a quick summary!",
    ),
    (
        "book_enrichment",
        "btw — I added a 📚 to that book mention. Tap it for ratings, a synopsis, and similar reads!",
    ),
    (
        "vibecheck",
        "btw — try `/vibecheck` for a quick server activity snapshot, or `/mystats` to see your own engagement stats!",
    ),
]

# ---------------------------------------------------------------------------
# Feature spotlight content
# ---------------------------------------------------------------------------

SPOTLIGHT_FEATURES: list[dict[str, str]] = [
    {
        "name": "📝 TL;DR Summaries",
        "description": (
            "When someone posts a long message, I add a 📝 reaction. "
            "Tap it to get a quick 2-3 bullet summary!"
        ),
        "example": "Write a long message (500+ chars) → tap 📝 → instant summary",
    },
    {
        "name": "📋 Link Summaries",
        "description": (
            "When someone shares a link, I add a 📋 reaction. "
            "Tap it to get a concise summary of the linked page."
        ),
        "example": "Share a news article → tap 📋 → key takeaways in seconds",
    },
    {
        "name": "📚 Book Enrichment",
        "description": (
            "Mention a book in #reading and I'll add a 📚 reaction. "
            "Tap it for ratings, a synopsis, and similar book recommendations!"
        ),
        "example": "\"Just started Dune\" in #reading → tap 📚 → full book info",
    },
    {
        "name": "📊 /vibecheck",
        "description": (
            "Get a quick snapshot of server activity — who's posting, "
            "which channels are hot, and the overall community vibe."
        ),
        "example": "Type `/vibecheck` → instant server health report",
    },
    {
        "name": "📈 /mystats",
        "description": (
            "See your personal engagement stats — message count, rank, "
            "top channels, peak hours, and fun facts."
        ),
        "example": "Type `/mystats` → your personal dashboard",
    },
    {
        "name": "🎉 /celebrate",
        "description": (
            "Celebrate a win or shout out a friend with a personalized "
            "celebration message and GIF."
        ),
        "example": "Type `/celebrate @friend landed the job!` → party time",
    },
    {
        "name": "🏆 Hall of Fame",
        "description": (
            "Messages that get lots of reactions automatically get nominated. "
            "Tap 🏆 to vote — enough votes and it's inducted into the Hall of Fame!"
        ),
        "example": "Post a banger → community votes 🏆 → immortalized",
    },
    {
        "name": "🔥 /trending",
        "description": (
            "See the hottest messages from the past day — the ones getting "
            "the most reactions and engagement."
        ),
        "example": "Type `/trending` → today's greatest hits",
    },
]

# Rate limit: max 1 tip per channel per 24 hours (in seconds)
_CHANNEL_TIP_COOLDOWN = 86400

# In-memory tracker: channel_id -> last_tip_timestamp
_channel_last_tip: dict[int, float] = {}


def _extract_domain(url: str) -> str:
    """Extract domain from a URL."""
    try:
        domain = url.split("://", 1)[1] if "://" in url else url
        domain = domain.split("/", 1)[0]
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.lower()
    except Exception:
        return ""


def _is_media_url(url: str) -> bool:
    """Return True if the URL path ends with a known media extension."""
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in _SKIP_EXTENSIONS)


class FeatureDiscoveryCog(PoolAwareCog):
    """Contextual feature tips and periodic feature spotlights."""

    CAPABILITIES = CogCapabilities(
        scheduled=[
            ScheduledCapability(
                name="Feature Spotlight",
                schedule=f"Every {cfg.FEATURE_SPOTLIGHT_INTERVAL_DAYS} days at 12 PM PT",
                description="Highlights an underused bot feature in the lobby",
                category=Category.SCHEDULED_DAILY,
            ),
        ],
    )

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.scheduler: AsyncIOScheduler | None = None
        self._spotlight_index = 0

    async def cog_load(self) -> None:
        await super().cog_load()
        if not cfg.FEATURE_DISCOVERY_ENABLED:
            log.info("FeatureDiscoveryCog disabled via FEATURE_DISCOVERY_ENABLED")
            return

        self.scheduler = AsyncIOScheduler(timezone=LA)
        trigger = IntervalTrigger(
            days=cfg.FEATURE_SPOTLIGHT_INTERVAL_DAYS,
            timezone=LA,
            start_date="2026-02-10 12:00:00",  # next spotlight
        )
        self.scheduler.add_job(self._post_spotlight_safe, trigger)
        self.scheduler.start()
        log.info(
            "FeatureDiscoveryCog scheduler started (every %d days at 12 PM PT)",
            cfg.FEATURE_SPOTLIGHT_INTERVAL_DAYS,
        )

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        await super().cog_unload()

    # ------------------------------------------------------------------
    # A. Contextual tips (on_message)
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    @require_pool
    async def on_message(self, message: discord.Message) -> None:
        """Detect patterns and offer one-time feature tips."""
        if not cfg.FEATURE_DISCOVERY_ENABLED:
            return
        if message.author.bot or message.guild is None:
            return
        if message.guild.id != cfg.GUILD_ID:
            return

        # Determine which tip to offer (first match wins)
        tip_key, tip_text = self._match_tip(message)
        if tip_key is None:
            return

        # Channel rate-limit: max 1 tip per channel per 24h
        now = time.time()
        last = _channel_last_tip.get(message.channel.id, 0)
        if now - last < _CHANNEL_TIP_COOLDOWN:
            return

        # Per-user dedup: check if user already received this tip
        already_sent = await self.pool.fetchval(
            """
            SELECT 1 FROM discord.feature_tip
            WHERE user_id = $1 AND tip_key = $2
            """,
            message.author.id,
            tip_key,
        )
        if already_sent:
            return

        # Send the tip
        try:
            await message.reply(tip_text, mention_author=False)
        except discord.HTTPException as exc:
            log.warning("Failed to send feature tip: %s", exc)
            return

        # Record tip as sent
        await self.pool.execute(
            """
            INSERT INTO discord.feature_tip (user_id, tip_key)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            message.author.id,
            tip_key,
        )

        _channel_last_tip[message.channel.id] = now
        log.info(
            "Sent feature tip '%s' to user %s in #%s",
            tip_key,
            message.author.id,
            getattr(message.channel, "name", "?"),
        )

    def _match_tip(
        self, message: discord.Message,
    ) -> tuple[str | None, str | None]:
        """Return (tip_key, tip_text) for the first matching pattern, or (None, None)."""
        content = message.content

        # 1. Long message -> TL;DR tip
        if len(content) >= LONG_MESSAGE_THRESHOLD:
            return "tldr", TIP_DEFINITIONS[0][1]

        # 2. URL (non-image host, non-media extension) -> link summary tip
        urls = URL_PATTERN.findall(content)
        valid_urls = [
            u for u in urls
            if not any(skip in _extract_domain(u) for skip in _SKIP_DOMAINS)
            and not _is_media_url(u)
        ]
        if valid_urls:
            return "link_summary", TIP_DEFINITIONS[1][1]

        # 3. Book mention in #reading channel
        if (
            cfg.READING_CHANNEL_ID
            and message.channel.id == cfg.READING_CHANNEL_ID
        ):
            return "book_enrichment", TIP_DEFINITIONS[2][1]

        # 4. Activity question -> vibecheck/mystats tip
        if ACTIVITY_PATTERN.search(content):
            return "vibecheck", TIP_DEFINITIONS[3][1]

        return None, None

    # ------------------------------------------------------------------
    # B. Periodic feature spotlight
    # ------------------------------------------------------------------

    async def _post_spotlight_safe(self) -> None:
        """Error-handling wrapper for the spotlight task."""
        try:
            await self._post_spotlight()
        except Exception as exc:
            log.exception("Feature spotlight task failed: %s", exc)

    @idempotent_task("feature_spotlight", daily_key)
    async def _post_spotlight(self) -> str:
        """Post a feature spotlight embed to the lobby."""
        await self.bot.wait_until_ready()

        channel_id = cfg.LOBBY_CHANNEL_ID
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            log.error("Feature spotlight channel %d not found", channel_id)
            return "error:channel_not_found"

        # Pick the next feature in rotation
        feature = SPOTLIGHT_FEATURES[self._spotlight_index % len(SPOTLIGHT_FEATURES)]
        self._spotlight_index += 1

        embed = discord.Embed(
            title=f"✨ Feature Spotlight: {feature['name']}",
            description=feature["description"],
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Try it",
            value=feature["example"],
            inline=False,
        )
        embed.set_footer(text="Gentlebot has lots of hidden talents — stay tuned for more!")

        await channel.send(embed=embed)
        log.info("Feature spotlight posted: %s", feature["name"])
        return f"posted:{feature['name']}"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FeatureDiscoveryCog(bot))
