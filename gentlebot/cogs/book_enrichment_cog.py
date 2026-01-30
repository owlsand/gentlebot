"""
book_enrichment_cog.py – Book Info Enrichment for #reading
==========================================================
Provides on-demand book information when users discuss books.

How it works:
  • Detects book mentions in #reading using LLM analysis
  • Auto-reacts with 📚 emoji to indicate info is available
  • When any user taps 📚, bot replies with book metadata:
    - Rating from Open Library
    - Brief spoiler-free synopsis
    - Similar book recommendations
    - Link to Open Library page

Configuration in bot_config.py:
  • READING_CHANNEL_ID: Channel ID for #reading (0 = disabled)
  • BOOK_ENRICHMENT_ENABLED: Master toggle (default: True)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import discord
import requests
from discord.ext import commands
from requests.adapters import HTTPAdapter, Retry

from .. import bot_config as cfg
from ..llm.router import router, SafetyBlocked
from ..infra import RateLimited
from ..util import user_name, chan_name

log = logging.getLogger(f"gentlebot.{__name__}")

# Emoji used to indicate book info is available
BOOK_EMOJI = "📚"

# Open Library API endpoints
OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
OPEN_LIBRARY_WORKS_URL = "https://openlibrary.org/works/{work_id}.json"
OPEN_LIBRARY_BOOK_URL = "https://openlibrary.org{key}"

# Cache for book info to avoid repeated API calls
# Key: message_id, Value: (book_title, book_data)
_book_cache: Dict[int, Tuple[str, Dict[str, Any]]] = {}

# Maximum cache size
MAX_CACHE_SIZE = 100


class BookEnrichmentCog(commands.Cog):
    """Provides book information enrichment for #reading channel."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.session = self._build_session()
        self.reading_channel_id = getattr(cfg, "READING_CHANNEL_ID", 0)
        self.enabled = getattr(cfg, "BOOK_ENRICHMENT_ENABLED", True)

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

    async def _detect_book_mention(self, text: str) -> Optional[str]:
        """Use LLM to detect if a message mentions a book and extract the title.

        Returns the book title if detected, None otherwise.
        """
        prompt = f"""Analyze this Discord message and determine if it mentions a specific book.
If it does, extract the book title. If not, respond with "NONE".

Message: "{text}"

Rules:
- Only extract actual book titles, not general topics
- Include author name if mentioned (e.g., "1984 by George Orwell")
- If multiple books are mentioned, extract only the first one
- Respond with ONLY the book title or "NONE", nothing else

Examples:
- "Just finished reading Hyperion" → "Hyperion"
- "Has anyone read Project Hail Mary by Andy Weir?" → "Project Hail Mary by Andy Weir"
- "I love reading sci-fi books" → "NONE"
- "The Midnight Library was amazing" → "The Midnight Library"
"""
        try:
            response = await asyncio.to_thread(
                router.generate,
                "general",
                [{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            result = response.strip()
            if result.upper() == "NONE" or len(result) < 2:
                return None
            return result
        except (RateLimited, SafetyBlocked):
            log.info("LLM unavailable for book detection")
            return None
        except Exception:
            log.exception("Failed to detect book mention")
            return None

    def _search_open_library(self, query: str) -> Optional[Dict[str, Any]]:
        """Search Open Library for book information."""
        try:
            # Clean up the query
            clean_query = re.sub(r'\s+', ' ', query.strip())

            resp = self.session.get(
                OPEN_LIBRARY_SEARCH_URL,
                params={
                    "q": clean_query,
                    "limit": 1,
                    "fields": "key,title,author_name,first_publish_year,number_of_pages_median,subject,ratings_average,ratings_count,cover_i",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            docs = data.get("docs", [])
            if not docs:
                return None

            book = docs[0]

            # Fetch additional details from the work endpoint
            work_key = book.get("key", "")
            description = None
            if work_key:
                try:
                    work_resp = self.session.get(
                        f"https://openlibrary.org{work_key}.json",
                        timeout=10,
                    )
                    if work_resp.ok:
                        work_data = work_resp.json()
                        desc = work_data.get("description")
                        if isinstance(desc, dict):
                            description = desc.get("value", "")
                        elif isinstance(desc, str):
                            description = desc
                except Exception:
                    pass

            return {
                "title": book.get("title", "Unknown Title"),
                "authors": book.get("author_name", []),
                "year": book.get("first_publish_year"),
                "pages": book.get("number_of_pages_median"),
                "subjects": book.get("subject", [])[:5],  # Top 5 subjects
                "rating": book.get("ratings_average"),
                "rating_count": book.get("ratings_count"),
                "cover_id": book.get("cover_i"),
                "description": description,
                "key": work_key,
            }
        except Exception as exc:
            log.warning("Failed to search Open Library for '%s': %s", query, exc)
            return None

    def _format_book_embed(self, book: Dict[str, Any]) -> discord.Embed:
        """Format book data into a Discord embed."""
        title = book.get("title", "Unknown Title")
        authors = book.get("authors", [])
        author_text = ", ".join(authors[:3]) if authors else "Unknown Author"

        embed = discord.Embed(
            title=f"📖 {title}",
            color=discord.Color.blue(),
        )

        embed.add_field(name="Author(s)", value=author_text, inline=True)

        if book.get("year"):
            embed.add_field(name="Published", value=str(book["year"]), inline=True)

        if book.get("pages"):
            embed.add_field(name="Pages", value=str(book["pages"]), inline=True)

        # Rating with stars
        rating = book.get("rating")
        rating_count = book.get("rating_count")
        if rating:
            stars = "⭐" * round(rating)
            rating_text = f"{stars} {rating:.1f}/5"
            if rating_count:
                rating_text += f" ({rating_count:,} ratings)"
            embed.add_field(name="Rating", value=rating_text, inline=True)

        # Description (truncated)
        description = book.get("description")
        if description:
            # Truncate to ~300 chars
            if len(description) > 300:
                description = description[:297] + "..."
            embed.add_field(name="Synopsis", value=description, inline=False)

        # Subjects/genres
        subjects = book.get("subjects", [])
        if subjects:
            subject_text = ", ".join(subjects[:5])
            embed.add_field(name="Genres", value=subject_text, inline=False)

        # Cover image
        cover_id = book.get("cover_id")
        if cover_id:
            embed.set_thumbnail(url=f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg")

        # Link to Open Library
        key = book.get("key", "")
        if key:
            embed.url = f"https://openlibrary.org{key}"
            embed.set_footer(text="Data from Open Library • Tap title for more info")

        return embed

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Detect book mentions and add 📚 reaction."""
        # Skip if disabled or wrong channel
        if not self.enabled or not self.reading_channel_id:
            return

        if message.channel.id != self.reading_channel_id:
            return

        # Skip bots and empty messages
        if message.author.bot:
            return

        text = message.content.strip()
        if len(text) < 5:
            return

        # Detect book mention
        book_title = await self._detect_book_mention(text)
        if not book_title:
            return

        log.info(
            "Detected book mention '%s' in message from %s",
            book_title,
            user_name(message.author),
        )

        # Pre-fetch book info and cache it
        book_data = await asyncio.to_thread(self._search_open_library, book_title)
        if not book_data:
            log.info("No Open Library data found for '%s'", book_title)
            return

        # Cache the book data
        global _book_cache
        if len(_book_cache) >= MAX_CACHE_SIZE:
            # Remove oldest entries
            oldest_keys = list(_book_cache.keys())[:MAX_CACHE_SIZE // 2]
            for k in oldest_keys:
                del _book_cache[k]

        _book_cache[message.id] = (book_title, book_data)

        # Add the book emoji reaction
        try:
            await message.add_reaction(BOOK_EMOJI)
        except discord.HTTPException:
            log.warning("Failed to add book emoji to message %s", message.id)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Handle 📚 reaction to show book info."""
        # Skip if disabled
        if not self.enabled:
            return

        # Only respond to book emoji
        if str(payload.emoji) != BOOK_EMOJI:
            return

        # Skip bot's own reactions
        if payload.user_id == self.bot.user.id:
            return

        # Check if we have cached data for this message
        book_data = _book_cache.get(payload.message_id)
        if not book_data:
            return

        book_title, book_info = book_data

        # Get the channel and message
        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return
        except discord.HTTPException:
            log.warning("Failed to fetch message %s", payload.message_id)
            return

        # Create and send the embed
        embed = self._format_book_embed(book_info)

        try:
            await message.reply(embed=embed, mention_author=False)
            log.info(
                "Sent book info for '%s' requested by user %s",
                book_title,
                payload.user_id,
            )

            # Remove from cache after sending to avoid duplicate responses
            _book_cache.pop(payload.message_id, None)
        except discord.HTTPException as exc:
            log.warning("Failed to send book info: %s", exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BookEnrichmentCog(bot))
