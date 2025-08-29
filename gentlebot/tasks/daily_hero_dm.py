from __future__ import annotations
import os
import logging
import asyncio

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

PROMPT_TEMPLATE = (
    "You are Gentlebot, a refined British butler announcing Discord honours.\n\n"
    "Compose a single-sentence direct message to {display_name} that:\n"
    "• greets the user (Good day / Greetings / Salutations / Well met)  \n"
    "• states they earned the “Daily Hero” role in Gentlefolk for yesterday’s contributions  \n"
    "• notes the role expires at midnight  \n"
    "• mentions this is their {ordinal} time receiving it  \n"
    "• contains no requests, tasks, or calls-to-action  \n"
    "• uses formal British-but-warm diction  \n"
    "• 25-30 words total\n"
    "Output only the sentence. No markdown, no extra lines."
)

FALLBACK_TEMPLATE = (
    "Good day, {username}. Your sterling contributions yesterday in Gentlefolk have earned you the Daily Hero role until midnight Pacific for the {ordinal} time. Bask accordingly. — Gentlebot 🤖"
)


class DailyHeroDMCog(commands.Cog):
    """Scheduler that DMs yesterday's Daily Hero at 9am Pacific, noting server name and win count."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.temperature = 0.7
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
        trigger = CronTrigger(hour=9, minute=0, timezone=LA)
        self.scheduler.add_job(self._send_dm, trigger)
        self.scheduler.start()
        log.info("DailyHero DM scheduler started")

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        if self.pool:
            await self.pool.close()
            self.pool = None

    def _ordinal(self, n: int) -> str:
        suffix = "th"
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    def _build_prompt(self, display_name: str, wins: int) -> str:
        ordinal = self._ordinal(wins)
        return PROMPT_TEMPLATE.format(display_name=display_name, ordinal=ordinal)

    def _fallback(self, name: str, wins: int) -> str:
        ordinal = self._ordinal(wins)
        return FALLBACK_TEMPLATE.format(username=name, ordinal=ordinal)

    def _is_valid(self, text: str) -> bool:
        words = text.split()
        return "Daily Hero" in text and 25 <= len(words) <= 30

    async def _generate_message(self, display_name: str, wins: int) -> str:
        prompt = self._build_prompt(display_name, wins)
        try:
            text = await asyncio.to_thread(
                router.generate,
                "scheduled",
                [{"role": "user", "content": prompt}],
                self.temperature,
            )
            text = text.strip().replace("\n", " ")
        except (RateLimited, SafetyBlocked) as e:
            log.warning("scheduled DM generation failed: %s", e)
            return self._fallback(display_name, wins)
        except Exception as e:
            log.exception("Generation failed: %s", e)
            return self._fallback(display_name, wins)

        if not self._is_valid(text):
            log.debug("Invalid Gemini message '%s'; using fallback", text)
            return self._fallback(display_name, wins)
        return text

    async def _win_count(self, role_id: int, user_id: int) -> int:
        if not self.pool:
            return 0
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) AS c FROM discord.role_event WHERE role_id=$1 AND user_id=$2 AND action=1",
            role_id,
            user_id,
        )
        return int(row["c"]) if row else 0

    async def _send_dm(self) -> None:
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            log.error("Guild not found")
            return
        role = guild.get_role(cfg.ROLE_DAILY_HERO)
        if not role:
            log.error("Daily Hero role not found")
            return
        for member in list(role.members):
            wins = await self._win_count(role.id, member.id) or 1
            message = await self._generate_message(member.display_name, wins)
            try:
                await member.send(message)
                log.info(
                    "Sent Daily Hero DM to %s: %s",
                    member.display_name,
                    message,
                )
            except discord.HTTPException:
                log.warning("Failed to DM Daily Hero %s", member)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailyHeroDMCog(bot))
