"""Scheduler that posts a daily haiku summarizing server chat."""
from __future__ import annotations
import logging
import asyncio
from datetime import datetime
from datetime import timedelta

import pytz
import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import discord
from discord.ext import commands

from .. import bot_config as cfg
from ..util import build_db_url
from ..llm.router import router, SafetyBlocked
from ..infra.quotas import RateLimited

log = logging.getLogger(f"gentlebot.{__name__}")

LA = pytz.timezone("America/Los_Angeles")


def build_prompt(day_str: str, corpus: str) -> dict:
    system = (
        "You are a concise poet. Write a single evocative haiku about the day’s Discord chat. "
        "Strict 5-7-5 syllables. No names, no @mentions, no links, no brand names. "
        "Use natural imagery; avoid slang and profanity."
    )
    user = (
        f"DATE: {day_str}\n"
        "TASK: Read the following conversation excerpts from today and produce ONE haiku.\n"
        "REQUIREMENTS: 5-7-5 syllables, English, safe for work, no proper names.\n"
        "OUTPUT: Only the haiku on three lines. No quotes, no preface.\n\n"
        "CONVERSATION START\n"
        f"{corpus}\n"
        "CONVERSATION END"
    )
    return {"system": system, "user": user}


class DailyHaikuCog(commands.Cog):
    """Scheduler that posts a daily haiku summary in the lobby at 10pm Pacific."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler: AsyncIOScheduler | None = None
        self.pool: asyncpg.Pool | None = None

    async def cog_load(self) -> None:
        url = build_db_url()
        if url:
            url = url.replace("postgresql+asyncpg://", "postgresql://")

            async def _init(conn: asyncpg.Connection) -> None:
                await conn.execute("SET search_path=discord,public")

            self.pool = await asyncpg.create_pool(url, init=_init)
        self.scheduler = AsyncIOScheduler(timezone=LA)
        trigger = CronTrigger(hour=22, minute=0, timezone=LA)
        self.scheduler.add_job(self._post_haiku, trigger)
        self.scheduler.start()
        log.info("DailyHaiku scheduler started")

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def _fetch_corpus(self, start: datetime, end: datetime) -> str:
        if not self.pool:
            return ""
        rows = await self.pool.fetch(
            """
            SELECT m.content
            FROM discord.message m
            JOIN discord.channel c ON m.channel_id = c.channel_id
            LEFT JOIN discord."user" u ON m.author_id = u.user_id
            WHERE m.guild_id = $1
              AND m.created_at >= $2 AND m.created_at < $3
              AND c.type = 0
              AND (c.nsfw IS FALSE OR c.nsfw IS NULL)
              AND (c.is_private IS FALSE OR c.is_private IS NULL)
              AND (u.is_bot IS NOT TRUE)
            """,
            cfg.GUILD_ID,
            start,
            end,
        )
        return "\n".join(r["content"] or "" for r in rows if r["content"])

    async def _post_haiku(self) -> None:
        await self.bot.wait_until_ready()
        now = datetime.now(tz=LA)
        start = datetime(now.year, now.month, now.day, tzinfo=LA)
        corpus = await self._fetch_corpus(start, now)
        if not corpus:
            log.info("No messages available for haiku generation")
            return
        prompt = build_prompt(start.strftime("%Y-%m-%d"), corpus)
        try:
            text = await asyncio.to_thread(
                router.generate,
                "scheduled",
                [
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": prompt["user"]},
                ],
            )
            text = text.strip()
        except (RateLimited, SafetyBlocked) as e:
            log.warning("scheduled haiku generation failed: %s", e)
            return
        except Exception:
            log.exception("Haiku generation failed")
            return
        channel = self.bot.get_channel(cfg.LOBBY_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            log.error("Lobby channel not found")
            return
        try:
            await channel.send(text)
        except discord.HTTPException:
            log.warning("Failed to post haiku")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailyHaikuCog(bot))
