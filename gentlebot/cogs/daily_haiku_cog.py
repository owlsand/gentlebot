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

    async def _fetch_corpus(self, start: datetime, end: datetime) -> tuple[str, int]:
        if not self.pool:
            return "", 0
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
        messages = [r["content"] or "" for r in rows if r["content"]]
        return "\n".join(messages), len(messages)

    async def _get_most_active_channel(self, start: datetime, end: datetime) -> int | None:
        """Find the most active text channel today based on message count."""
        if not self.pool:
            return None
        row = await self.pool.fetchrow(
            """
            SELECT m.channel_id, COUNT(*) as msg_count
            FROM discord.message m
            JOIN discord.channel c ON m.channel_id = c.channel_id
            LEFT JOIN discord."user" u ON m.author_id = u.user_id
            WHERE m.guild_id = $1
              AND m.created_at >= $2 AND m.created_at < $3
              AND c.type = 0
              AND (c.nsfw IS FALSE OR c.nsfw IS NULL)
              AND (c.is_private IS FALSE OR c.is_private IS NULL)
              AND (u.is_bot IS NOT TRUE)
            GROUP BY m.channel_id
            ORDER BY msg_count DESC
            LIMIT 1
            """,
            cfg.GUILD_ID,
            start,
            end,
        )
        return row["channel_id"] if row else None

    async def _channel_has_activity_since_last_haiku(self, channel_id: int, today_start: datetime) -> bool:
        """Check if the target channel has had any activity today."""
        if not self.pool:
            return True  # Default to posting if we can't check
        row = await self.pool.fetchrow(
            """
            SELECT COUNT(*) as cnt
            FROM discord.message m
            LEFT JOIN discord."user" u ON m.author_id = u.user_id
            WHERE m.channel_id = $1
              AND m.created_at >= $2
              AND (u.is_bot IS NOT TRUE)
            """,
            channel_id,
            today_start,
        )
        return row["cnt"] > 0 if row else False

    async def _post_haiku(self) -> None:
        await self.bot.wait_until_ready()
        now = datetime.now(tz=LA)
        start = LA.localize(datetime(now.year, now.month, now.day))
        corpus, count = await self._fetch_corpus(start, now)
        if count <= 50:
            log.info("Only %d messages collected; skipping haiku", count)
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

        # Smart channel targeting: check if lobby has activity, otherwise use most active channel
        target_channel_id = cfg.LOBBY_CHANNEL_ID
        lobby_active = await self._channel_has_activity_since_last_haiku(cfg.LOBBY_CHANNEL_ID, start)

        if not lobby_active:
            log.info("Lobby channel inactive today, finding most active channel")
            most_active = await self._get_most_active_channel(start, now)
            if most_active:
                target_channel_id = most_active
                log.info("Redirecting haiku to channel %d (most active today)", target_channel_id)
            else:
                log.info("No active channels found; skipping haiku post")
                return

        channel = self.bot.get_channel(target_channel_id)
        if not isinstance(channel, discord.TextChannel):
            log.error("Target channel %d not found or not a text channel", target_channel_id)
            return
        try:
            await channel.send(text)
            log.info("Haiku posted to channel %s (%d)", channel.name, target_channel_id)
        except discord.HTTPException:
            log.warning("Failed to post haiku to channel %d", target_channel_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailyHaikuCog(bot))
