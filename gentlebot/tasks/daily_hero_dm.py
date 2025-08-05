from __future__ import annotations
import os
import logging

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import discord
from discord.ext import commands
from huggingface_hub import InferenceClient

from .. import bot_config as cfg

log = logging.getLogger(f"gentlebot.{__name__}")

LA = pytz.timezone("America/Los_Angeles")

PROMPT_TEMPLATE = (
    "You are Gentlebot, a refined British butler announcing Discord honours.\n\n"
    "Compose a single-sentence direct message to {display_name} that:\n"
    "• greets the user (Good day / Greetings / Salutations / Well met)  \n"
    "• states they earned the “Daily Hero” role for yesterday’s contributions  \n"
    "• notes the role expires at midnight  \n"
    "• contains no requests, tasks, or calls-to-action  \n"
    "• uses formal British-but-warm diction  \n"
    "• 25-30 words total\n"
    "Output only the sentence. No markdown, no extra lines."
)

FALLBACK_TEMPLATE = (
    "Good day, {username}. Your sterling contributions yesterday have earned you the Daily Hero role until midnight Pacific. Bask accordingly. — Gentlebot 🤖"
)


class DailyHeroDMCog(commands.Cog):
    """Scheduler that DMs yesterday's Daily Hero at 8am Pacific."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        token = os.getenv("HF_API_TOKEN")
        if not token:
            raise RuntimeError("HF_API_TOKEN is not set")
        self.model_id = os.getenv("HF_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
        self.hf_client = InferenceClient(api_key=token, provider="together")
        self.scheduler: AsyncIOScheduler | None = None

    async def cog_load(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone=LA)
        trigger = CronTrigger(hour=8, minute=0, timezone=LA)
        self.scheduler.add_job(self._send_dm, trigger)
        self.scheduler.start()
        log.info("DailyHero DM scheduler started")

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None

    def _build_prompt(self, display_name: str) -> str:
        return PROMPT_TEMPLATE.format(display_name=display_name)

    def _fallback(self, name: str) -> str:
        return FALLBACK_TEMPLATE.format(username=name)

    def _is_valid(self, text: str) -> bool:
        words = text.split()
        return "Daily Hero" in text and 25 <= len(words) <= 30

    async def _generate_message(self, display_name: str) -> str:
        prompt = self._build_prompt(display_name)
        try:
            response = self.hf_client.text_generation(
                prompt,
                model=self.model_id,
                max_new_tokens=60,
                temperature=0.7,
                top_p=0.9,
                repetition_penalty=1.2,
            )
            text = response.strip().replace("\n", " ")
        except Exception as e:
            log.exception("HF generation failed: %s", e)
            return self._fallback(display_name)

        if not self._is_valid(text):
            log.debug("Invalid HF message '%s'; using fallback", text)
            return self._fallback(display_name)
        return text

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
            message = await self._generate_message(member.display_name)
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
