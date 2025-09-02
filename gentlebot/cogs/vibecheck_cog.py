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
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

import discord
from discord import app_commands
from discord.ext import commands

from .. import bot_config as cfg
from ..util import chan_name, user_name

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


class VibeCheckCog(commands.Cog):
    """Slash command `/vibecheck` returning a server vibe report."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- statistics helpers -------------------------------------------------
    async def _gather_messages(
        self, guild: discord.Guild, start: datetime, end: datetime
    ) -> list[discord.Message]:
        msgs: list[discord.Message] = []
        for channel in guild.text_channels:
            # include only public channels readable by @everyone
            perms = channel.permissions_for(guild.me)
            if not (perms.read_messages and perms.read_message_history):
                continue
            if not channel.permissions_for(guild.default_role).read_messages:
                continue
            try:
                async for msg in channel.history(limit=None, after=start, before=end):
                    msgs.append(msg)
            except Exception as e:  # pragma: no cover - permission edge cases
                log.warning("History fetch failed for %s: %s", chan_name(channel), e)
        return msgs

    def _media_bucket(self, msg: discord.Message) -> str:
        """Classify message into link/image/text buckets."""
        text = msg.content or ""
        has_link = bool(re.search(r"https?://", text))
        has_image = any(
            (a.content_type or "").startswith("image/") for a in msg.attachments
        )
        if has_link:
            return "link"
        if has_image:
            return "image"
        return "text"

    # --- core command -------------------------------------------------------
    @app_commands.command(name="vibecheck", description="Summarize server vibes")
    async def vibecheck(self, interaction: discord.Interaction) -> None:
        """Inspect recent activity and return a vibe report."""
        log.info(
            "/vibecheck invoked by %s in %s",
            user_name(interaction.user),
            chan_name(interaction.channel),
        )
        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            await interaction.response.send_message("Guild not configured", ephemeral=True)
            return

        now = datetime.now(timezone.utc)
        cur_start = now - timedelta(days=7)
        prior_start = now - timedelta(days=14)
        baseline_start = now - timedelta(days=44)

        msgs = await self._gather_messages(guild, baseline_start, now)

        cur_msgs: list[discord.Message] = []
        prior_msgs: list[discord.Message] = []
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
        posters = Counter(m.author.id for m in cur_msgs if not m.author.bot)
        top_posters = posters.most_common(3)

        reactions_total = sum(sum(r.count for r in m.reactions) for m in cur_msgs)
        rxn_per_msg = reactions_total / cur_count if cur_count else 0.0

        # channel hotness -----------------------------------------------------
        channel_msgs: dict[int, list[discord.Message]] = defaultdict(list)
        for m in cur_msgs:
            channel_msgs[m.channel.id].append(m)
        channel_counts = {cid: len(lst) for cid, lst in channel_msgs.items()}
        prior_channel_counts: Counter[int] = Counter(m.channel.id for m in prior_msgs)
        top_channels = sorted(
            channel_counts.items(), key=lambda kv: kv[1], reverse=True
        )[:3]

        # media mix -----------------------------------------------------------
        mix_ctr = Counter(self._media_bucket(m) for m in cur_msgs)
        link_pct = mix_ctr.get("link", 0) / cur_count * 100 if cur_count else 0
        img_pct = mix_ctr.get("image", 0) / cur_count * 100 if cur_count else 0
        text_pct = mix_ctr.get("text", 0) / cur_count * 100 if cur_count else 0

        # unanswered questions ------------------------------------------------
        unanswered: tuple[discord.TextChannel, discord.Message] | None = None
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
                    if reply.author.id != msg.author.id:
                        answered = True
                        break
                if not answered:
                    unanswered = (msg.channel, msg)
                    break
            if unanswered:
                break

        unanswered_penalty = 10 if unanswered else 0

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
        poster_ratio = len(posters) / max(1, len(set(m.author.id for m in prior_msgs)))
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
            member = guild.get_member(uid)
            name = member.display_name if member else f"<@{uid}>"
            lines.append(f"{medal} @{name} ({cnt} msgs)")
        if not top_posters:
            lines.append("No posters found")

        lines.append("")
        lines.append("*The Hotness*")
        for cid, count in top_channels:
            channel = guild.get_channel(cid)
            prior = prior_channel_counts.get(cid, 0)
            delta = ((count / max(1, prior)) - 1) * 100
            rising = ", ⬆ rising" if count >= 20 and count / max(1, prior) >= 1.5 else ""
            topics = self._derive_topics(channel_msgs[cid])
            lines.append(
                f"- #{channel.name} › \"{topics[0]}\", \"{topics[1]}\" "
                f"({count} msgs, {delta:.0f}%{rising})"
            )
        lines.append(
            f"- Media Mix: {link_pct:.0f}% links, {img_pct:.0f}% images/gifs, {text_pct:.0f}% text only"
        )

        lines.append("")
        lines.append("*Better Friendship*")
        if unanswered:
            ch, msg = unanswered
            lines.append(
                f"• Unanswered question in {chan_name(ch)} from {user_name(msg.author)}"
            )
        else:
            lines.append("• Everyone's getting answers!")
        if top_channels:
            ch = guild.get_channel(top_channels[0][0])
            lines.append(f"• Keep the heat going with a mini-demo thread in #{ch.name}")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # ------------------------------------------------------------------
    def _derive_topics(self, messages: Iterable[discord.Message]) -> tuple[str, str]:
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

