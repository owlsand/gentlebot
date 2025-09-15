"""Automatically post Big Dumper updates when Cal Raleigh homers."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import aiohttp
import discord
from discord.ext import commands, tasks

from .sports_cog import PLAYER_ID, STATS_TIMEOUT
from .sports_cog import SportsCog
from .. import bot_config as cfg

log = logging.getLogger(f"gentlebot.{__name__}")


class BigDumperWatcherCog(commands.Cog):
    """Background task posting `/bigdumper` after new home runs."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        timeout = aiohttp.ClientTimeout(total=STATS_TIMEOUT)
        self.session = aiohttp.ClientSession(timeout=timeout)
        self.last_hr = 0

    async def cog_load(self) -> None:
        try:
            self.last_hr = await self._fetch_hr()
        except Exception as exc:  # pragma: no cover - network
            log.warning("Failed to fetch initial HR count: %s", exc)
        self.check_task.start()

    async def cog_unload(self) -> None:
        self.check_task.cancel()
        await self.session.close()

    async def _fetch_hr(self) -> int:
        year = datetime.now().year
        url = f"https://statsapi.mlb.com/api/v1/people/{PLAYER_ID}/stats"
        params = {"stats": "season", "group": "hitting", "season": year}
        for attempt in range(3):
            try:
                async with self.session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return int(data["stats"][0]["splits"][0]["stat"].get("homeRuns", 0))
            except aiohttp.ClientError as exc:
                if attempt == 2:
                    raise exc
                await asyncio.sleep(1)
        return 0

    @tasks.loop(minutes=10)
    async def check_task(self) -> None:
        await self.bot.wait_until_ready()
        try:
            hr = await self._fetch_hr()
        except aiohttp.ClientError as exc:  # pragma: no cover - network
            log.warning("Failed to fetch HR count: %s", exc)
            return
        except Exception as exc:  # pragma: no cover - network
            log.exception("Failed to fetch HR count: %s", exc)
            return
        if hr <= self.last_hr:
            return
        self.last_hr = hr
        sports_cog = self.bot.get_cog("SportsCog")
        if not isinstance(sports_cog, SportsCog):
            log.error("SportsCog not loaded; cannot send update")
            return
        embed = await sports_cog.build_bigdumper_embed()
        if embed is None:
            return
        channel = self.bot.get_channel(getattr(cfg, "LOBBY_CHANNEL_ID", 0))
        if not isinstance(channel, discord.TextChannel):
            log.error("Big Dumper channel not found: %s", getattr(cfg, "LOBBY_CHANNEL_ID", 0))
            return
        try:
            await channel.send(embed=embed)
        except Exception as exc:  # pragma: no cover - network
            log.exception("Failed to send Big Dumper update: %s", exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BigDumperWatcherCog(bot))
