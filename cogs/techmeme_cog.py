"""TechmemeCog – display the latest stories from Techmeme's RSS feed."""
from __future__ import annotations

import asyncio
import logging
import html
import re
from datetime import timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
import feedparser
from bs4 import BeautifulSoup

from util import chan_name

# Use a hierarchical logger so messages propagate to the main gentlebot logger
log = logging.getLogger(f"gentlebot.{__name__}")

TECHMEME_RSS = "https://www.techmeme.com/feed.xml"


class TechmemeCog(commands.Cog):
    """Slash command to show recent Techmeme headlines."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="techmeme", description="Show the latest Techmeme headlines")
    @app_commands.describe(ephemeral="Whether the response should be ephemeral")
    async def techmeme(self, interaction: discord.Interaction, ephemeral: bool = False):
        log.info("/techmeme invoked by %s in %s", interaction.user.id, chan_name(interaction.channel))
        await interaction.response.defer(thinking=True, ephemeral=ephemeral)
        try:
            feed = await asyncio.to_thread(feedparser.parse, TECHMEME_RSS)
            raw_entries = feed.entries
        except Exception:  # pragma: no cover - network
            log.exception("Failed to fetch Techmeme RSS")
            await interaction.followup.send(
                "Could not fetch Techmeme headlines right now.", ephemeral=ephemeral
            )
            return

        entries: list[feedparser.FeedParserDict] = []
        seen: set[str] = set()
        for e in raw_entries:
            guid = e.get("guid")
            if guid in seen:
                continue
            seen.add(guid)
            entries.append(e)
            if len(entries) == 5:
                break

        if not entries:
            await interaction.followup.send("No headlines found.", ephemeral=ephemeral)
            return

        blocks: list[str] = []
        for idx, e in enumerate(entries, start=1):
            title_html = e.get("title", "")
            title_text = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
            m = re.search(r"\(([^()]*)\)\s*$", title_text)
            if m:
                source = m.group(1)
                headline_text = title_text[: m.start()].rstrip()
            else:
                source = ""
                headline_text = title_text

            summary_html = e.get("summary", "")
            soup = BeautifulSoup(summary_html, "html.parser")
            first_anchor = None
            for a in soup.find_all("a", href=True):
                if a.find("img") or "techmeme.com" in a["href"]:
                    continue
                first_anchor = a
                break

            summary_text = headline_text
            if first_anchor:
                tail_text = BeautifulSoup("".join(str(x) for x in first_anchor.next_siblings), "html.parser").get_text(" ", strip=True)
                summary_text = str(first_anchor)
                if tail_text:
                    summary_text += " " + tail_text

            anchors = [a for a in soup.find_all("a", href=True) if not a.find("img") and "techmeme.com" not in a["href"]]
            related_links = len(anchors) - 1 if len(anchors) > 1 else 0
            related = f"{related_links} links" if related_links else "—"

            pub = e.get("published") or e.get("pubDate") or ""
            local_time = pub
            try:
                dt = parsedate_to_datetime(pub)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt = dt.astimezone(ZoneInfo("America/Los_Angeles"))
                local_time = dt.strftime("%b %-d, %-I:%M%p").replace("AM", "am").replace("PM", "pm")
            except Exception:
                pass

            categories = e.get("tags")
            if categories:
                tags = ", ".join(t.get("term", "") for t in categories if t.get("term"))
            else:
                tags = "—"

            block = "\n".join(
                [
                    f"**{idx}. [{headline_text}]({e.link})**" + (f" ({source})" if source else ""),
                    summary_text,
                    "",
                    f"_Posted {local_time} · Tags: {tags}",
                    f"More coverage: {related}",
                ]
            )
            blocks.append(block)

        last_updated = feed.feed.get("lastBuildDate", "")
        message = "\n\n".join(blocks) + f"\n\nLast updated: {last_updated}"
        if len(message) <= 2000:
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            # Discord enforces a hard 2000 character limit on messages.
            for chunk in [message[i : i + 1900] for i in range(0, len(message), 1900)]:
                await interaction.followup.send(chunk, ephemeral=ephemeral)


async def setup(bot: commands.Bot):
    await bot.add_cog(TechmemeCog(bot))

