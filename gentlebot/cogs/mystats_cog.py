"""Personal engagement stats via /mystats slash command."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from .. import bot_config as cfg
from ..infra import PoolAwareCog
from ..capabilities import (
    CogCapabilities,
    CommandCapability,
    Category,
)
from ..queries import engagement as eq

log = logging.getLogger(f"gentlebot.{__name__}")

# Timeframe choices: label shown in Discord -> timedelta for asyncpg
TIMEFRAMES: dict[str, timedelta] = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "all": timedelta(days=36500),  # effectively "all time"
}

TIMEFRAME_LABELS: dict[str, str] = {
    "7d": "Last 7 Days",
    "30d": "Last 30 Days",
    "90d": "Last 90 Days",
    "all": "All Time",
}


def _format_percentile(pct: float | None) -> str | None:
    """Format a 0.0–1.0 PERCENT_RANK as a friendly 'Top X%' string.

    Returns None for bottom-half users or missing data to avoid discouragement.
    """
    if pct is None:
        return None
    top_pct = round((1 - pct) * 100)
    if top_pct > 50:
        return None
    return f"Top {max(top_pct, 1)}%"


def _format_hour(hour: int | None) -> str:
    """Format an hour (0–23) as a friendly 12-hour time string."""
    if hour is None:
        return "N/A"
    suffix = "AM" if hour < 12 else "PM"
    display = hour % 12 or 12
    return f"{display} {suffix} PT"


class MyStatsCog(PoolAwareCog):
    """Ephemeral /mystats command showing personal engagement stats."""

    CAPABILITIES = CogCapabilities(
        commands=[
            CommandCapability(
                name="mystats",
                description="/mystats [timeframe] — View your personal engagement stats",
                category=Category.ENGAGEMENT,
            ),
        ],
    )

    @app_commands.command(
        name="mystats",
        description="View your personal engagement stats (only you can see this)",
    )
    @app_commands.describe(timeframe="Time window to analyze")
    @app_commands.choices(
        timeframe=[
            app_commands.Choice(name="Last 7 days", value="7d"),
            app_commands.Choice(name="Last 30 days", value="30d"),
            app_commands.Choice(name="Last 90 days", value="90d"),
            app_commands.Choice(name="All time", value="all"),
        ],
    )
    async def mystats(
        self,
        interaction: discord.Interaction,
        timeframe: str = "30d",
    ) -> None:
        """Display personal engagement stats in an ephemeral embed."""
        if not cfg.MYSTATS_ENABLED:
            await interaction.response.send_message(
                "This command is currently disabled.", ephemeral=True,
            )
            return

        log.info(
            "/mystats invoked by %s (timeframe=%s)",
            interaction.user,
            timeframe,
        )
        await interaction.response.defer(ephemeral=True)

        interval = TIMEFRAMES.get(timeframe, timedelta(days=30))
        uid = interaction.user.id

        embed = await self._build_stats_embed(interaction.user, uid, interval, timeframe)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _build_stats_embed(
        self,
        member: discord.User | discord.Member,
        uid: int,
        interval: timedelta,
        timeframe: str,
    ) -> discord.Embed:
        """Build the full stats embed for a user."""
        msg_count = await eq.user_message_count(self.pool, uid, interval)

        # Early exit: no activity
        if msg_count == 0:
            embed = discord.Embed(
                title=f"Your Stats — {TIMEFRAME_LABELS.get(timeframe, timeframe)}",
                description=(
                    "No activity in this period — try a longer timeframe!"
                ),
                color=discord.Color.light_grey(),
            )
            embed.set_footer(text="Only you can see this.")
            return embed

        # Fetch all data concurrently via individual awaits
        # (asyncpg shares the connection pool so these are efficient)
        msg_pct = await eq.user_message_percentile(self.pool, uid, interval)
        reacts_received = await eq.user_reactions_received(self.pool, uid, interval)
        react_pct = await eq.user_reaction_percentile(self.pool, uid, interval)
        top_emojis = await eq.user_top_emojis_received(self.pool, uid, interval)
        top_channels = await eq.user_top_channels(self.pool, uid, interval)
        peak_hour = await eq.user_peak_hour(self.pool, uid, interval)
        hof_count = await eq.user_hall_of_fame_count(self.pool, uid)
        fun_facts = await eq.user_fun_facts(self.pool, uid)

        # Streak data (query directly — lightweight)
        streak_current = 0
        streak_best = 0
        if self.pool:
            row = await self.pool.fetchrow(
                """
                SELECT current_streak, longest_streak
                FROM discord.user_streak
                WHERE user_id = $1
                """,
                uid,
            )
            if row:
                streak_current = row["current_streak"]
                streak_best = row["longest_streak"]

        # Build embed
        embed = discord.Embed(
            title=f"Your Stats — {TIMEFRAME_LABELS.get(timeframe, timeframe)}",
            color=discord.Color.blurple(),
        )

        # Messages field
        msg_text = f"**{msg_count:,}** messages"
        pct_str = _format_percentile(msg_pct)
        if pct_str:
            msg_text += f"\n{pct_str} of posters"
        embed.add_field(name="Messages", value=msg_text, inline=True)

        # Reactions field
        react_text = f"**{reacts_received:,}** reactions"
        react_pct_str = _format_percentile(react_pct)
        if react_pct_str:
            react_text += f"\n{react_pct_str}"
        embed.add_field(name="Reactions Received", value=react_text, inline=True)

        # Streak field
        streak_text = f"**{streak_current}**-day current streak\nBest: **{streak_best}** days"
        embed.add_field(name="Streak", value=streak_text, inline=True)

        # Top channels
        if top_channels:
            chan_parts = [f"#{name} ({cnt:,})" for _, name, cnt in top_channels]
            embed.add_field(
                name="Your Top Channels",
                value=" \u00b7 ".join(chan_parts),
                inline=False,
            )

        # Vibe section
        vibe_lines = []
        vibe_lines.append(f"Peak hour: **{_format_hour(peak_hour)}**")
        if top_emojis:
            emoji_parts = [f"{emoji} x{cnt}" for emoji, cnt in top_emojis]
            emoji_str = " \u00b7 ".join(emoji_parts)
            vibe_lines.append(f"Top reactions: {emoji_str}")
        if hof_count > 0:
            vibe_lines.append(f"Hall of Fame entries: **{hof_count}**")
        embed.add_field(name="Your Vibe", value="\n".join(vibe_lines), inline=False)

        # Fun facts
        facts_lines = []
        first_seen = fun_facts.get("first_seen_at")
        if first_seen:
            if hasattr(first_seen, "date"):
                seen_date = first_seen.date()
            else:
                seen_date = first_seen
            days_ago = (datetime.now(timezone.utc).date() - seen_date).days
            facts_lines.append(
                f"Member since **{seen_date.strftime('%b %d, %Y')}** ({days_ago:,} days)"
            )
        lifetime = fun_facts.get("lifetime_messages", 0)
        if lifetime:
            facts_lines.append(f"**{lifetime:,}** lifetime messages")
        longest_msg = fun_facts.get("longest_message_len", 0)
        if longest_msg:
            facts_lines.append(f"Longest message: **{longest_msg:,}** characters")
        if facts_lines:
            embed.add_field(name="Fun Facts", value="\n".join(facts_lines), inline=False)

        embed.set_footer(text="Only you can see this.")
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MyStatsCog(bot))
