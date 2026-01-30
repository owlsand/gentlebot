"""
link_summarizer_cog.py – Universal Link Summarization
======================================================
Provides on-demand summaries for any shared link.

How it works:
  • Detects links in messages
  • Auto-reacts with 📋 emoji to indicate summary is available
  • When any user taps 📋, bot fetches and summarizes the link
  • Caches summaries to avoid re-fetching

Configuration in bot_config.py:
  • LINK_SUMMARIZER_ENABLED: Master toggle (default: True)
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import discord
import requests
from bs4 import BeautifulSoup
from discord.ext import commands
from requests.adapters import HTTPAdapter, Retry

from .. import bot_config as cfg
from ..llm.router import router, SafetyBlocked
from ..infra import RateLimited
from ..util import user_name, chan_name
from ..capabilities import CogCapabilities, ReactionCapability

log = logging.getLogger(f"gentlebot.{__name__}")

# Emoji used to indicate summary is available
SUMMARY_EMOJI = "📋"

# URL regex pattern - matches http/https URLs
URL_PATTERN = re.compile(
    r'https?://[^\s<>"\')\]]+',
    re.IGNORECASE
)

# Domains to skip (image/GIF hosts that aren't summarizable)
SKIP_DOMAINS = {
    "tenor.com",
    "giphy.com",
    "imgur.com",
    "gfycat.com",
    "media.discordapp.net",
    "cdn.discordapp.com",
    "i.redd.it",
    "v.redd.it",
    "preview.redd.it",
    "i.imgur.com",
    "media.tenor.com",
    "c.tenor.com",
}

# Cache for summaries to avoid repeated API calls
# Key: message_id, Value: (url, summary)
_summary_cache: Dict[int, Tuple[str, str]] = {}

# Maximum cache size
MAX_CACHE_SIZE = 200


def _extract_domain(url: str) -> str:
    """Extract the domain from a URL."""
    try:
        # Remove protocol
        domain = url.split("://", 1)[1] if "://" in url else url
        # Remove path
        domain = domain.split("/", 1)[0]
        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.lower()
    except Exception:
        return ""


def _should_skip_url(url: str) -> bool:
    """Check if URL should be skipped (image/GIF hosts)."""
    domain = _extract_domain(url)
    return any(skip in domain for skip in SKIP_DOMAINS)


class LinkSummarizerCog(commands.Cog):
    """Provides link summarization via reaction interface."""

    CAPABILITIES = CogCapabilities(
        reactions=[
            ReactionCapability(
                emoji="📋",
                trigger="Shared links",
                description="React to get an AI-generated summary of the linked page",
            ),
        ]
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.session = self._build_session()
        self.enabled = getattr(cfg, "LINK_SUMMARIZER_ENABLED", True)

    def _build_session(self) -> requests.Session:
        """Build a requests session with retry logic."""
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _fetch_page_content(self, url: str, max_chars: int = 8000) -> Optional[str]:
        """Fetch and extract text content from a URL."""
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
            resp = self.session.get(url, headers=headers, timeout=15)
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            if "text" not in content_type and "html" not in content_type:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove script, style, nav, footer elements
            for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
                tag.decompose()

            # Try to get main content
            main_content = None
            for selector in ["article", "main", '[role="main"]', ".post-content", ".article-content"]:
                main_content = soup.select_one(selector)
                if main_content:
                    break

            if main_content:
                text = " ".join(main_content.stripped_strings)
            else:
                text = " ".join(soup.stripped_strings)

            # Get title
            title = ""
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)

            # Combine title and content
            if title:
                text = f"Title: {title}\n\n{text}"

            return text[:max_chars] if text else None

        except Exception as exc:
            log.warning("Failed to fetch page content from '%s': %s", url, exc)
            return None

    async def _summarize_content(self, url: str, content: str) -> str:
        """Use LLM to summarize the page content."""
        domain = _extract_domain(url)

        prompt = f"""Summarize this web page content into a brief, useful summary.

URL: {url}
Domain: {domain}

Content:
{content[:6000]}

Requirements:
- Start with "**TL;DR:** " followed by 2-3 sentences capturing the key point
- If there are specific quotes, facts, or numbers, include the most important one
- Keep total response under 400 characters
- Don't include the URL in your response
- If the content seems incomplete or unclear, summarize what's available"""

        try:
            response = await asyncio.to_thread(
                router.generate,
                "general",
                [{"role": "user", "content": prompt}],
                temperature=0.4,
            )
            return response.strip()
        except (RateLimited, SafetyBlocked):
            log.info("LLM unavailable for link summary")
            return "Summary unavailable. Try again later."
        except Exception:
            log.exception("Failed to generate summary")
            return "Could not generate summary for this link."

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Detect links and add 📋 reaction."""
        # Skip if disabled
        if not self.enabled:
            return

        # Skip bots
        if message.author.bot:
            return

        # Find URLs in message
        urls = URL_PATTERN.findall(message.content)
        if not urls:
            return

        # Filter out skip domains
        valid_urls = [url for url in urls if not _should_skip_url(url)]
        if not valid_urls:
            return

        # Use the first valid URL
        url = valid_urls[0]

        log.info(
            "Detected link '%s' in message from %s",
            url[:100],
            user_name(message.author),
        )

        # Pre-fetch page content and cache the URL (not the summary yet)
        global _summary_cache
        if len(_summary_cache) >= MAX_CACHE_SIZE:
            # Remove oldest entries
            oldest_keys = list(_summary_cache.keys())[:MAX_CACHE_SIZE // 2]
            for k in oldest_keys:
                del _summary_cache[k]

        # Store the URL for later summarization
        _summary_cache[message.id] = (url, "")

        # Add the summary emoji reaction
        try:
            await message.add_reaction(SUMMARY_EMOJI)
        except discord.HTTPException:
            log.warning("Failed to add summary emoji to message %s", message.id)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Handle 📋 reaction to show summary."""
        # Skip if disabled
        if not self.enabled:
            return

        # Only respond to summary emoji
        if str(payload.emoji) != SUMMARY_EMOJI:
            return

        # Skip bot's own reactions
        if payload.user_id == self.bot.user.id:
            return

        # Check if we have cached data for this message
        cached = _summary_cache.get(payload.message_id)
        if not cached:
            return

        url, existing_summary = cached

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
            # Fetch content and generate summary
            content = await asyncio.to_thread(self._fetch_page_content, url)
            if not content:
                summary = f"Could not fetch content from {_extract_domain(url)}. The page may require JavaScript or authentication."
            else:
                summary = await self._summarize_content(url, content)

            # Cache the summary
            _summary_cache[payload.message_id] = (url, summary)

        # Send the summary as a reply
        domain = _extract_domain(url)
        response = f"📋 **Summary** ({domain})\n\n{summary}"

        try:
            await message.reply(response, mention_author=False)
            log.info(
                "Sent link summary for '%s' requested by user %s",
                url[:80],
                payload.user_id,
            )

            # Remove from cache after sending to avoid duplicate responses
            _summary_cache.pop(payload.message_id, None)
        except discord.HTTPException as exc:
            log.warning("Failed to send link summary: %s", exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LinkSummarizerCog(bot))
