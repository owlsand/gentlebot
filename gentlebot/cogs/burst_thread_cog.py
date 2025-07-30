"""Automatically fork intense conversations into threads."""
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import asyncpg
import discord
from discord.ext import commands

from ..util import build_db_url, int_env

try:
    from huggingface_hub import InferenceClient
except Exception:  # pragma: no cover - optional dependency may be missing
    InferenceClient = None  # type: ignore

log = logging.getLogger(f"gentlebot.{__name__}")


class BurstThreadCog(commands.Cog):
    """Detect bursty chat and open a thread."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.window = timedelta(minutes=10)
        self.cooldown = timedelta(minutes=int_env("BURST_COOLDOWN_MINUTES", 30))
        self.threshold = 10
        self.bot_id = 1128886406488530966
        self.history: dict[int, deque[tuple[datetime, int, str]]] = defaultdict(
            lambda: deque(maxlen=50)
        )
        self.last_trigger: dict[int, datetime] = defaultdict(
            lambda: datetime.min.replace(tzinfo=timezone.utc)
        )
        token = os.getenv("HF_API_TOKEN")
        if InferenceClient and token:
            self.hf_client = InferenceClient(provider="together", api_key=token)
        else:
            self.hf_client = None
        self.model_id = os.getenv("HF_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
        self.max_tokens = int_env("HF_MAX_TOKENS", 10)
        self.temperature = float(os.getenv("HF_TEMPERATURE", 0.6))
        self.top_p = float(os.getenv("HF_TOP_P", 0.9))
        self.pool: asyncpg.Pool | None = None

    async def cog_load(self) -> None:
        url = build_db_url()
        if not url:
            return
        url = url.replace("postgresql+asyncpg://", "postgresql://")

        async def _init(conn: asyncpg.Connection) -> None:
            await conn.execute("SET search_path=discord,public")

        self.pool = await asyncpg.create_pool(url, init=_init)

    async def cog_unload(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def _summarize(self, text: str) -> str:
        """Return a four-word topic summary."""
        if not self.hf_client:
            return "Chat Burst Thread"
        prompt = (
            "Summarize the main topic of these messages in four words or less.\n" + text
        )
        try:
            result = await asyncio.to_thread(
                self.hf_client.chat.completions.create,
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
            )
            content = getattr(result.choices[0].message, "content", "").strip()
            return content or "Chat Burst Thread"
        except Exception as exc:  # pragma: no cover - network
            log.exception("HF summary failed: %s", exc)
            return "Chat Burst Thread"

    async def _log(self, channel_id: int, thread_id: int, msgs: int, authors: int) -> None:
        if not self.pool:
            return
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
        try:
            await channel.send(f"📈 Burst detected – opened {thread.mention}")
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
        if len(authors) < 2:
            return
        last = self.last_trigger[msg.channel.id]
        if now - last < self.cooldown:
            return
        self.last_trigger[msg.channel.id] = now
        hist.clear()
        await self._open_thread(msg.channel, records)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BurstThreadCog(bot))
