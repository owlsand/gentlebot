"""Gentle ping when the server has been unusually quiet."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from .. import bot_config as cfg
from ..llm.router import router, SafetyBlocked
from ..infra.quotas import RateLimited
from ..util import chan_name

log = logging.getLogger(f"gentlebot.{__name__}")


class QuietServerCog(commands.Cog):
    """Monitor guild activity and send a gentle check-in when things are quiet."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.threshold = 10
        self._quiet_active = False

    async def cog_load(self) -> None:
        self._check_quiet.start()

    async def cog_unload(self) -> None:
        self._check_quiet.cancel()

    @tasks.loop(minutes=60)
    async def _check_quiet(self) -> None:
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            log.warning("Guild %s not found; skipping quiet check", cfg.GUILD_ID)
            return

        member = guild.me
        if member is None:
            log.debug("Bot member not available yet; skipping quiet check")
            return

        now = datetime.now(timezone.utc)
        day_cutoff = now - timedelta(hours=24)
        week_cutoff = now - timedelta(days=7)

        total_24h = 0
        weekly_counts: dict[int, int] = {}
        channel_cache: dict[int, discord.TextChannel] = {}

        for channel in guild.text_channels:
            perms = channel.permissions_for(member)
            if not (perms.read_messages and perms.read_message_history):
                continue
            try:
                async for message in channel.history(limit=1000, after=week_cutoff):
                    created_at = message.created_at
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    if created_at < week_cutoff:
                        continue

                    channel_id = channel.id
                    weekly_counts[channel_id] = weekly_counts.get(channel_id, 0) + 1
                    channel_cache[channel_id] = channel

                    if created_at >= day_cutoff:
                        total_24h += 1
            except discord.Forbidden:
                log.debug("Missing history permissions for %s", chan_name(channel))
            except discord.HTTPException as exc:
                log.warning("History fetch failed for %s: %s", chan_name(channel), exc)
            except Exception:
                log.exception("Unexpected error fetching history for %s", chan_name(channel))

        if not weekly_counts:
            log.info("No activity data collected; skipping quiet check")
            self._quiet_active = False
            return

        if not self._should_trigger(total_24h):
            return

        channel_id = self._select_most_active_channel(weekly_counts)
        if channel_id is None:
            log.info("Unable to select a channel for quiet check-in")
            return

        channel = channel_cache.get(channel_id)
        if channel is None:
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                log.info("Channel %s unavailable for quiet check-in", channel_id)
                return

        await self._send_check_in(channel, total_24h, weekly_counts[channel_id])

    @_check_quiet.before_loop
    async def _before_check_quiet(self) -> None:
        await self.bot.wait_until_ready()

    async def _send_check_in(
        self,
        channel: discord.TextChannel,
        total_24h: int,
        weekly_total: int,
    ) -> None:
        messages = [
            {
                "role": "user",
                "content": (
                    "Compose a short Discord message as Gentlebot. "
                    "The server has been unusually quiet with just "
                    f"{total_24h} messages in the last 24 hours. "
                    "You are posting in the busiest channel from the last 7 days, "
                    f"#{channel.name}, which saw {weekly_total} messages. "
                    "Acknowledge the quiet vibe and gently mention that it makes "
                    "Gentlebot feel a little lonely and sad, but stay supportive and "
                    "encouraging. Offer a soft invitation to chat without pressuring "
                    "anyone. Keep it under four sentences, avoid emojis, hashtags, "
                    "and @mentions. Return only the final message ready for Discord."
                ),
            }
        ]

        try:
            text = await asyncio.to_thread(router.generate, "scheduled", messages, 0.6)
        except RateLimited as exc:
            log.warning("Gemini rate limited for quiet check: %s", exc)
            return
        except SafetyBlocked as exc:
            log.warning("Gemini safety blocked quiet check: %s", exc)
            return
        except Exception:
            log.exception("Gemini generation failed for quiet check")
            return

        text = text.strip()
        if not text:
            log.info("Generated quiet check-in was empty; skipping")
            return

        if len(text) > 1900:
            text = text[:1900]

        try:
            await channel.send(text)
        except discord.HTTPException as exc:
            log.warning("Failed to send quiet check-in to %s: %s", chan_name(channel), exc)
        else:
            log.info(
                "Posted quiet check-in to %s after %d messages in 24h",
                chan_name(channel),
                total_24h,
            )

    def _should_trigger(self, total_24h: int) -> bool:
        if total_24h < self.threshold:
            if not self._quiet_active:
                self._quiet_active = True
                return True
            return False

        self._quiet_active = False
        return False

    @staticmethod
    def _select_most_active_channel(counts: dict[int, int]) -> int | None:
        best_channel: int | None = None
        best_count = -1
        for channel_id, count in counts.items():
            if count > best_count:
                best_channel = channel_id
                best_count = count
            elif (
                count == best_count
                and best_channel is not None
                and channel_id < best_channel
            ):
                best_channel = channel_id
        return best_channel


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QuietServerCog(bot))
