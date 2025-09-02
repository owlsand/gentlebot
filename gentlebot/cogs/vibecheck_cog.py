"""VibeCheckCog - summarize recent server activity with an overall score.

This cog implements the `/vibecheck` slash command.  It inspects recent
messages in public channels and produces a compact text report including an
overall score, activity bars, top posters, hot channels and media mix.  The
command posts an ephemeral response.
"""
from __future__ import annotations

import logging
import math
import re
import statistics
import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

from .. import bot_config as cfg
from ..db import get_pool
from ..util import chan_name, user_name
from ..llm.router import router, RateLimited, SafetyBlocked

# Hierarchical logger as required by project guidelines
log = logging.getLogger(f"gentlebot.{__name__}")

BAR_CHARS = "▁▂▃▄▅▆▇"


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(val, hi))


def z_to_bar(z: float) -> str:
    """Map a z-score to one of seven block characters."""
    z = clamp(z, -2.5, 2.5)
    idx = int(round((z + 2.5) / 5 * (len(BAR_CHARS) - 1)))
    return BAR_CHARS[idx]


def gini(values: Sequence[int]) -> float:
    """Return the Gini coefficient for a list of positive numbers."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    height, area = 0, 0
    for v in sorted_vals:
        height += v
        area += height - v / 2
    fair_area = height * len(values) / 2
    return 1 - area / fair_area if fair_area else 0.0


@dataclass
class ArchivedMessage:
    """Lightweight representation of an archived Discord message."""

    channel_id: int
    channel_name: str
    author_id: int
    author_name: str
    content: str
    created_at: datetime
    has_image: bool
    reactions: int


class VibeCheckCog(commands.Cog):
    """Slash command `/vibecheck` returning a server vibe report."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: asyncpg.Pool | None = None

    async def cog_load(self) -> None:
        try:
            self.pool = await get_pool()
        except RuntimeError:
            log.warning("VibeCheckCog disabled due to missing database URL")
            self.pool = None

    async def cog_unload(self) -> None:
        self.pool = None

    # --- statistics helpers -------------------------------------------------
    async def _gather_messages(self, start: datetime, end: datetime) -> list[ArchivedMessage]:
        if not self.pool:
            return []
        rows = await self.pool.fetch(
            """
            SELECT m.channel_id, c.name AS channel_name,
                   m.author_id, u.display_name, m.content, m.created_at,
                   EXISTS (
                       SELECT 1 FROM discord.message_attachment a
                       WHERE a.message_id = m.message_id
                         AND (a.content_type ILIKE 'image/%' OR a.url ~ '\\.(?:png|jpe?g|gif)$')
                   ) AS has_image,
                   COALESCE(
                       (SELECT COUNT(*) FILTER (WHERE action = 0) - COUNT(*) FILTER (WHERE action = 1)
                        FROM discord.reaction_event r
                        WHERE r.message_id = m.message_id),
                       0
                   ) AS reactions
            FROM discord.message m
            JOIN discord.channel c ON m.channel_id = c.channel_id
            LEFT JOIN discord."user" u ON m.author_id = u.user_id
            WHERE m.guild_id = $1
              AND m.created_at >= $2 AND m.created_at < $3
              AND c.type = 0
              AND (c.nsfw IS FALSE OR c.nsfw IS NULL)
              AND (u.is_bot IS NOT TRUE)
            """,
            cfg.GUILD_ID,
            start,
            end,
        )
        msgs: list[ArchivedMessage] = []
        for r in rows:
            msgs.append(
                ArchivedMessage(
                    channel_id=r["channel_id"],
                    channel_name=r["channel_name"] or str(r["channel_id"]),
                    author_id=r["author_id"],
                    author_name=r["display_name"] or str(r["author_id"]),
                    content=r["content"] or "",
                    created_at=r["created_at"],
                    has_image=bool(r["has_image"]),
                    reactions=int(r["reactions"] or 0),
                )
            )
        return msgs

    def _media_bucket(self, msg: ArchivedMessage) -> str:
        """Classify message into link/image/text buckets."""
        text = msg.content or ""
        has_link = bool(re.search(r"https?://", text))
        if has_link:
            return "link"
        if msg.has_image:
            return "image"
        return "text"

    async def _friendship_tips(
        self,
        cur_msgs: Iterable[ArchivedMessage],
        prior_msgs: Iterable[ArchivedMessage],
    ) -> list[str]:
        """Return bullet tips on friendship using an LLM."""

        def _fmt(messages: Iterable[ArchivedMessage]) -> str:
            lines = []
            for m in messages:
                if not m.content:
                    continue
                name = getattr(m, "author_name", None)
                if not name:
                    name = user_name(getattr(m, "author", None))
                lines.append(f"{name}: {m.content}")
            return "\n".join(lines)

        cur_text = _fmt(cur_msgs)
        prior_text = _fmt(prior_msgs)
        prompt = (
            "Using these Discord messages, give one suggestion for how members can "
            "be better friends. Then briefly state whether they are being better "
            "friends in the current period compared to the prior period. Respond "
            "with two bullet points.\n\n"
            f"Current period messages:\n{cur_text}\n\nPrior period messages:\n{prior_text}"
        )
        data = [{"role": "user", "content": prompt}]
        try:
            resp = await asyncio.to_thread(router.generate, "general", data, 0.6)
            lines = [l.strip("-• ") for l in resp.splitlines() if l.strip()]
            return [f"• {l}" for l in lines[:2]]
        except (RateLimited, SafetyBlocked):
            return ["• Friendship tips currently unavailable"]
        except Exception as exc:  # pragma: no cover - unexpected errors
            log.exception("Friendship tip generation failed: %s", exc)
            return ["• Friendship tips currently unavailable"]

    # --- core command -------------------------------------------------------
    @app_commands.command(name="vibecheck", description="Summarize server vibes")
    async def vibecheck(self, interaction: discord.Interaction) -> None:
        """Inspect recent activity and return a vibe report."""
        log.info(
            "/vibecheck invoked by %s in %s",
            user_name(interaction.user),
            chan_name(interaction.channel),
        )
        if not self.pool:
            await interaction.response.send_message(
                "Message archive unavailable", ephemeral=True
            )
            return

        now = datetime.now(timezone.utc)
        cur_start = now - timedelta(days=7)
        prior_start = now - timedelta(days=14)
        baseline_start = now - timedelta(days=44)

        msgs = await self._gather_messages(baseline_start, now)

        cur_msgs: list[ArchivedMessage] = []
        prior_msgs: list[ArchivedMessage] = []
        baseline_days: defaultdict[datetime.date, int] = defaultdict(int)

        for m in msgs:
            ts = m.created_at
            if ts >= cur_start:
                cur_msgs.append(m)
            elif ts >= prior_start:
                prior_msgs.append(m)
            else:
                baseline_days[ts.date()] += 1

        cur_count = len(cur_msgs)
        prior_count = len(prior_msgs)

        # activity statistics -------------------------------------------------
        cur_per_day = cur_count / 7
        baseline_counts = list(baseline_days.values())
        if len(baseline_counts) < 2:
            baseline_counts = [0, 0]
        base_mean = statistics.mean(baseline_counts)
        base_std = statistics.stdev(baseline_counts) if len(baseline_counts) > 1 else 0
        z = (cur_per_day - base_mean) / base_std if base_std else 0.0
        bar = z_to_bar(z)
        delta_pct = (cur_count / max(1, prior_count)) - 1

        # poster statistics ---------------------------------------------------
        posters = Counter(m.author_id for m in cur_msgs)
        top_posters = posters.most_common(3)
        author_names = {m.author_id: m.author_name for m in cur_msgs}

        reactions_total = sum(m.reactions for m in cur_msgs)
        rxn_per_msg = reactions_total / cur_count if cur_count else 0.0

        # channel hotness -----------------------------------------------------
        channel_msgs: dict[int, list[ArchivedMessage]] = defaultdict(list)
        for m in cur_msgs:
            channel_msgs[m.channel_id].append(m)
        channel_counts = {cid: len(lst) for cid, lst in channel_msgs.items()}
        prior_channel_counts: Counter[int] = Counter(m.channel_id for m in prior_msgs)
        channel_names = {m.channel_id: m.channel_name for m in cur_msgs}
        top_channels = sorted(
            channel_counts.items(), key=lambda kv: kv[1], reverse=True
        )[:3]

        # media mix -----------------------------------------------------------
        mix_ctr = Counter(self._media_bucket(m) for m in cur_msgs)
        link_pct = mix_ctr.get("link", 0) / cur_count * 100 if cur_count else 0
        img_pct = mix_ctr.get("image", 0) / cur_count * 100 if cur_count else 0
        text_pct = mix_ctr.get("text", 0) / cur_count * 100 if cur_count else 0

        # unanswered questions ------------------------------------------------
        has_unanswered = False
        for cid, messages in channel_msgs.items():
            messages.sort(key=lambda m: m.created_at)
            for msg in reversed(messages):
                if not msg.content or not msg.content.strip().endswith("?"):
                    continue
                cutoff = msg.created_at + timedelta(hours=12)
                answered = False
                for reply in messages:
                    if reply.created_at <= msg.created_at or reply.created_at > cutoff:
                        continue
                    if reply.author_id != msg.author_id:
                        answered = True
                        break
                if not answered:
                    has_unanswered = True
                    break
            if has_unanswered:
                break

        unanswered_penalty = 10 if has_unanswered else 0

        # overall score -------------------------------------------------------
        # Activity
        activity_score = clamp((z + 2.5) / 5.0, 0, 1) * 100
        # Engagement (simple scale from reactions per message)
        engagement_score = clamp(rxn_per_msg / 3, 0, 1) * 100
        # Breadth
        breadth_val = clamp(
            len(posters) / math.sqrt(max(1, cur_count)), 0, 1
        ) + (1 - gini(list(posters.values()))) / 2
        breadth_score = clamp(breadth_val / 2, 0, 1) * 100
        # Momentum
        vol_ratio = cur_count / max(1, prior_count)
        poster_ratio = len(posters) / max(1, len(set(m.author_id for m in prior_msgs)))
        momentum_score = clamp((vol_ratio + poster_ratio) / 2 - 1, 0, 1) * 100
        # Hygiene
        hygiene_score = max(0, 100 - unanswered_penalty)

        overall = (
            activity_score * 0.30
            + engagement_score * 0.25
            + breadth_score * 0.20
            + momentum_score * 0.15
            + hygiene_score * 0.10
        )
        overall = int(clamp(overall, 0, 100))

        # assemble output -----------------------------------------------------
        lines: list[str] = []
        lines.append("*Vibe Check*")
        lines.append(
            f"*Gentlefolk* ({now.strftime('%b %-d')}) ▷ {overall}/100 Overall Score"
        )
        lines.append(
            f"Activity Level: {bar}  (↑ {delta_pct*100:.0f}% vs prior)  | "
            f"{len(posters)} Total Posters | {rxn_per_msg:.2f} Reactions/Msg"
        )
        lines.append("")
        lines.append("*Top Posters*")
        medals = ["🥇", "🥈", "🥉"]
        for medal, (uid, cnt) in zip(medals, top_posters):
            name = author_names.get(uid, str(uid))
            lines.append(f"{medal} @{name} ({cnt} msgs)")
        if not top_posters:
            lines.append("No posters found")

        lines.append("")
        lines.append("*The Hotness*")
        for cid, count in top_channels:
            prior = prior_channel_counts.get(cid, 0)
            delta = ((count / max(1, prior)) - 1) * 100
            rising = ", ⬆ rising" if count >= 20 and count / max(1, prior) >= 1.5 else ""
            topics = self._derive_topics(channel_msgs[cid])
            name = channel_names.get(cid, str(cid))
            lines.append(
                f"- #{name} › \"{topics[0]}\", \"{topics[1]}\" "
                f"({count} msgs, {delta:.0f}%{rising})"
            )
        lines.append(
            f"- Media Mix: {link_pct:.0f}% links, {img_pct:.0f}% images/gifs, {text_pct:.0f}% text only"
        )

        lines.append("")
        lines.append("*Better Friendship*")
        tips = await self._friendship_tips(cur_msgs, prior_msgs)
        lines.extend(tips)

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # ------------------------------------------------------------------
    def _derive_topics(self, messages: Iterable[ArchivedMessage]) -> tuple[str, str]:
        """Return two naive topic words extracted from message text."""
        words: Counter[str] = Counter()
        stop = {
            "the",
            "and",
            "that",
            "with",
            "this",
            "have",
            "what",
            "your",
            "from",
        }
        for msg in messages:
            for w in re.findall(r"[a-zA-Z]{4,}", msg.content.lower()):
                if w not in stop:
                    words[w] += 1
        top = [w for w, _ in words.most_common(2)]
        return (top + ["..."] * 2)[:2]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VibeCheckCog(bot))

