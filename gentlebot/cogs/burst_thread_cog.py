"""Automatically fork intense conversations into threads."""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timezone

import discord
from discord.ext import commands

from ..infra import (
    BurstThreadConfig,
    PoolAwareCog,
    RateLimited,
    get_config,
    get_logger,
    log_errors,
    require_pool,
)
from ..llm.router import SafetyBlocked, router

log = get_logger(__name__)


class BurstThreadCog(PoolAwareCog):
    """Detect bursty chat and open a thread."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        config = get_config().burst_thread
        self.window = config.window
        self.cooldown = config.cooldown
        self.threshold = config.message_threshold
        self.min_authors = config.min_authors
        self.bot_id = 1128886406488530966
        self.history: dict[int, deque[tuple[datetime, int, str]]] = defaultdict(
            lambda: deque(maxlen=50)
        )
        self.last_trigger: dict[int, datetime] = defaultdict(
            lambda: datetime.min.replace(tzinfo=timezone.utc)
        )
        self.max_tokens = 10
        self.temperature = get_config().llm.temperature
        self.alert_tokens = 50

    async def _summarize(self, text: str) -> str:
        """Return a four-word topic summary."""
        prompt = (
            "Summarize the main topic of these messages in four words or less.\n" + text
        )
        try:
            return await asyncio.to_thread(
                router.generate,
                "general",
                [{"role": "user", "content": prompt}],
                self.temperature,
            )
        except (RateLimited, SafetyBlocked) as exc:
            log.warning("Summary blocked: %s", exc)
        except Exception as exc:  # pragma: no cover - network
            log.exception("Summary failed: %s", exc)
        return "Chat Burst Thread"

    async def _alert_text(self, topic: str, thread_mention: str) -> str:
        """Generate an enthusiastic notice suggesting a thread."""
        prompt = (
            "The chat topic is: "
            + topic
            + ".\nWrite two short sentences. First, enthusiastically observe the topic. "
            "Second, politely suggest moving the conversation to a thread to avoid "
            "blowing up everyone's notifications, using the placeholder <THREAD> "
            "where the thread mention should go."
        )
        try:
            content = await asyncio.to_thread(
                router.generate,
                "general",
                [{"role": "user", "content": prompt}],
                self.temperature,
            )
            if content:
                content = content.replace("<THREAD>", thread_mention)
                return "📈 " + content
        except (RateLimited, SafetyBlocked) as exc:
            log.warning("Alert text blocked: %s", exc)
        except Exception as exc:  # pragma: no cover - network
            log.exception("Alert text failed: %s", exc)
        return (
            "📈 Wow, looks like you're getting pretty into "
            f"{topic}! Here's a thread if you want to take it offline "
            "to avoid blowing up everyone else's notifications: "
            f"{thread_mention}"
        )

    @require_pool
    async def _log(self, channel_id: int, thread_id: int, msgs: int, authors: int) -> None:
        await self.pool.execute(
            """
            INSERT INTO burst_log (triggered_at, channel_id, thread_id, msg_count, author_count)
            VALUES (now(), $1, $2, $3, $4)
            """,
            channel_id,
            thread_id,
            msgs,
            authors,
        )

    async def _open_thread(
        self,
        channel: discord.TextChannel,
        records: list[tuple[datetime, int, str]],
    ) -> None:
        text = "\n".join(r[2] for r in records if r[2])
        name = await self._summarize(text)
        try:
            thread = await channel.create_thread(name=name, auto_archive_duration=1440)
        except Exception:
            log.exception("Failed to create burst thread")
            return
        topic = name.lower()
        msg = await self._alert_text(topic, thread.mention)
        try:
            await channel.send(msg)
        except Exception:
            log.exception("Failed to send burst notice")
        guild = getattr(channel, "guild", None)
        if guild:
            for _, uid, _ in records:
                member = guild.get_member(uid)
                if member:
                    try:
                        await thread.add_user(member)
                    except Exception as exc:  # pragma: no cover - join failure ok
                        log.warning("Failed to add %s to burst thread: %s", uid, exc)
        await self._log(channel.id, thread.id, len(records), len({r[1] for r in records}))

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message) -> None:
        if not isinstance(msg.channel, discord.TextChannel):
            return
        if msg.author.bot or msg.author.id == self.bot_id:
            return
        if msg.type is not discord.MessageType.default:
            return
        now = msg.created_at.replace(tzinfo=timezone.utc)
        rec = (now, msg.author.id, msg.content)
        hist = self.history[msg.channel.id]
        hist.append(rec)
        cutoff = now - self.window
        while hist and hist[0][0] < cutoff:
            hist.popleft()
        records = list(hist)
        if len(records) < self.threshold:
            return
        authors = {r[1] for r in records}
        if len(authors) < self.min_authors:
            return
        last = self.last_trigger[msg.channel.id]
        if now - last < self.cooldown:
            return
        self.last_trigger[msg.channel.id] = now
        hist.clear()
        await self._open_thread(msg.channel, records)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BurstThreadCog(bot))
