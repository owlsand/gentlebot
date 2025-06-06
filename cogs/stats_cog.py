from __future__ import annotations
import logging
import asyncio
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import random
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import discord
from discord import app_commands
from discord.ext import commands

import bot_config as cfg
from util import chan_name

log = logging.getLogger(__name__)

class StatsCog(commands.Cog):
    """Slash command to show recent message activity stats."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _period_key(dt: datetime, window: str) -> date:
        if window == "weeks":
            return dt.date() - timedelta(days=dt.weekday())
        if window == "months":
            return date(dt.year, dt.month, 1)
        return dt.date()
    async def _gather_stats(self, window: str, per_channel: int = 1000):
        """Collect message, reaction and event stats for the given time window."""
        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            return None

        span_days = {
            "days": 30,
            "weeks": 16 * 7,
            "months": 12 * 30,
        }[window]

        now = datetime.now(timezone.utc)
        after = now - timedelta(days=span_days * 2)
        start_current = now - timedelta(days=span_days)

        u_curr: defaultdict[discord.Member, int] = defaultdict(int)
        u_prev: defaultdict[discord.Member, int] = defaultdict(int)
        ch_curr: defaultdict[discord.TextChannel, int] = defaultdict(int)
        ch_prev: defaultdict[discord.TextChannel, int] = defaultdict(int)
        reactions_curr = 0
        reactions_prev = 0
        reactions_sent_curr: defaultdict[discord.Member, int] = defaultdict(int)
        reactions_received_curr: defaultdict[discord.Member, int] = defaultdict(int)
        longest_msg: tuple[discord.Member | None, int] = (None, 0)
        per_period_msgs: defaultdict[date, defaultdict[discord.Member, int]] = defaultdict(lambda: defaultdict(int))
        per_period_users: defaultdict[date, set[int]] = defaultdict(set)

        for channel in guild.text_channels:
            try:
                async for msg in channel.history(limit=per_channel, after=after):
                    target_curr = msg.created_at >= start_current
                    user_map = u_curr if target_curr else u_prev
                    chan_map = ch_curr if target_curr else ch_prev
                    user_map[msg.author] += 1
                    chan_map[channel] += 1

                    if target_curr:
                        pkey = self._period_key(msg.created_at, window)
                        per_period_msgs[pkey][msg.author] += 1
                        per_period_users[pkey].add(msg.author.id)
                        length = len(msg.content)
                        if length > longest_msg[1]:
                            longest_msg = (msg.author, length)

                    # reactions on this message
                    for reaction in msg.reactions:
                        try:
                            count = reaction.count
                        except Exception as e:
                            log.exception("Reaction count failed for %s: %s", reaction.message.id, e)
                            continue
                        if target_curr:
                            reactions_curr += count
                            reactions_received_curr[msg.author] += count
                        else:
                            reactions_prev += count
            except discord.Forbidden as e:
                log.warning("History fetch failed for channel %s: %s", chan_name(channel), e)
            except Exception as e:
                log.exception("History fetch failed for channel %s: %s", chan_name(channel), e)

        per_period_active = {d: len(u) for d, u in per_period_users.items()}

        events_curr = 0
        events_prev = 0
        for event in guild.scheduled_events:
            if not event.start_time:
                continue
            if event.start_time >= start_current:
                events_curr += 1
            elif event.start_time >= after:
                events_prev += 1

        return {
            "users_curr": u_curr,
            "users_prev": u_prev,
            "channels_curr": ch_curr,
            "channels_prev": ch_prev,
            "period_msgs": per_period_msgs,
            "period_active": per_period_active,
            "reactions_curr": reactions_curr,
            "reactions_prev": reactions_prev,
            "reactions_sent_curr": reactions_sent_curr,
            "reactions_recv_curr": reactions_received_curr,
            "longest": longest_msg,
            "events_curr": events_curr,
            "events_prev": events_prev,
        }

    def _messages_chart_png(
        self,
        period_msgs: dict[date, dict[discord.Member, int]],
        periods: list[date],
        window: str,
    ) -> io.BytesIO:
        """Stacked bar chart of message counts grouped by user."""
        dates = periods
        # Determine top contributors overall
        totals: defaultdict[discord.Member, int] = defaultdict(int)
        for day_counts in period_msgs.values():
            for user, cnt in day_counts.items():
                totals[user] += cnt
        top_users = [u for u, _ in sorted(totals.items(), key=lambda x: x[1], reverse=True)[:5]]

        plt.style.use("dark_background")
        fig, ax = plt.subplots(figsize=(7, 3.5))
        colors = plt.get_cmap("tab10").colors
        bottom = [0] * len(dates)
        for idx, user in enumerate(top_users):
            vals = [period_msgs.get(d, {}).get(user, 0) for d in dates]
            ax.bar(
                dates,
                vals,
                bottom=bottom,
                label=user.display_name,
                color=colors[idx % len(colors)],
                edgecolor="white",
                linewidth=0.3,
            )
            bottom = [b + v for b, v in zip(bottom, vals)]

        # aggregate the rest as "Other"
        others = []
        for i, d in enumerate(dates):
            total = sum(period_msgs[d].values())
            others.append(total - bottom[i])
        if any(others):
            ax.bar(
                dates,
                others,
                bottom=bottom,
                label="Other",
                color=colors[len(top_users) % len(colors)],
                edgecolor="white",
                linewidth=0.3,
            )

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(labelsize=8)
        ax.legend(fontsize=8, ncol=2, loc="upper left")
        title_map = {"days": "Day", "weeks": "Week", "months": "Month"}
        ax.set_title(f"Messages by {title_map[window]}", fontsize=10)
        fig.tight_layout(pad=1.0)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        buf.seek(0)
        return buf

    def _users_chart_png(self, period_active: dict[date, int], periods: list[date], window: str) -> io.BytesIO:
        """Bar chart of active user counts."""
        dates = periods
        counts = [period_active.get(d, 0) for d in dates]
        plt.style.use("dark_background")
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.bar(dates, counts, color="#007acc", edgecolor="white", linewidth=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(labelsize=8)
        title_map = {"days": "Day", "weeks": "Week", "months": "Month"}
        ax.set_title(f"Active Users by {title_map[window]}", fontsize=10)
        fig.tight_layout(pad=1.0)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        buf.seek(0)
        return buf

    def _channels_chart_png(self, channel_counts: dict[discord.TextChannel, int]) -> io.BytesIO:
        """Bar chart of message counts per channel."""
        channels = sorted(channel_counts.items(), key=lambda x: x[1], reverse=True)
        names = [f"#{ch.name}" for ch, _ in channels]
        counts = [c for _, c in channels]
        plt.style.use("dark_background")
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.bar(names, counts, color="#007acc", edgecolor="white", linewidth=0.3)
        ax.tick_params(axis="x", rotation=45, labelsize=8)
        ax.tick_params(axis="y", labelsize=8)
        ax.set_title("Messages by Channel", fontsize=10)
        fig.tight_layout(pad=1.0)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        buf.seek(0)
        return buf

    async def _engagement_background(
        self,
        interaction: discord.Interaction,
        time_window: str,
        chart: app_commands.Choice[str] | None,
    ) -> None:
        """Gather stats in the background and send the resulting embed."""
        stats = await self._gather_stats(time_window, per_channel=None)
        if not stats:
            try:
                await interaction.followup.send("Guild not found.", ephemeral=True)
            except discord.HTTPException:
                if interaction.channel:
                    await interaction.channel.send("Guild not found.")
            return

        u_curr = stats["users_curr"]
        u_prev = stats["users_prev"]
        ch_curr = stats["channels_curr"]
        ch_prev = stats["channels_prev"]

        msgs_curr = sum(u_curr.values())
        msgs_prev = sum(u_prev.values())
        reacts_curr = stats["reactions_curr"]
        reacts_prev = stats["reactions_prev"]

        events_curr = stats["events_curr"]
        events_prev = stats["events_prev"]

        active_users = len(u_curr)
        active_users_prev = len(u_prev)
        active_channels = len(ch_curr)
        active_channels_prev = len({ch for ch, c in ch_prev.items() if c > 0})

        def delta(a: int, b: int) -> str:
            diff = a - b
            sign = "+" if diff >= 0 else ""
            return f"{sign}{diff}"

        def avg(val: int, div: int) -> int:
            return round(val / div) if div else 0

        metrics = [
            f"Active Users: {active_users} ({delta(active_users, active_users_prev)})",
            f"Active Channels: {active_channels} ({delta(active_channels, active_channels_prev)})",
            f"Messages: {msgs_curr} ({delta(msgs_curr, msgs_prev)})",
            f"Reactions: {reacts_curr} ({delta(reacts_curr, reacts_prev)})",
            f"Events: {events_curr} ({delta(events_curr, events_prev)})",
            f"Messages/User: {avg(msgs_curr, active_users)} ({delta(avg(msgs_curr, active_users), avg(msgs_prev, active_users_prev))})",
            f"Reactions/User: {avg(reacts_curr, active_users)} ({delta(avg(reacts_curr, active_users), avg(reacts_prev, active_users_prev))})",
            f"Messages/Channel: {avg(msgs_curr, active_channels)} ({delta(avg(msgs_curr, active_channels), avg(msgs_prev, active_channels_prev))})",
        ]

        top_channel = max(ch_curr.items(), key=lambda x: x[1]) if ch_curr else (None, 0)
        quiet_channels = [c for c, cnt in ch_curr.items() if cnt == min(ch_curr.values())] if ch_curr else []
        quiet_channel = random.choice(quiet_channels) if quiet_channels else (None)

        top_member = max(u_curr.items(), key=lambda x: x[1]) if u_curr else (None, 0)
        top_reactor = (
            max(stats["reactions_sent_curr"].items(), key=lambda x: x[1])
            if stats["reactions_sent_curr"]
            else (None, 0)
        )
        longest_msg = stats["longest"][0]
        longest_len = stats["longest"][1]

        bait_ratio = 0
        bait_user = None
        for user, msg_count in u_curr.items():
            recv = stats["reactions_recv_curr"].get(user, 0)
            ratio = recv / msg_count if msg_count else 0
            if ratio > bait_ratio:
                bait_ratio = ratio
                bait_user = user

        highlights = []
        if top_channel[0]:
            highlights.append(f"Loudest Channel: #{top_channel[0].name} – {top_channel[1]}")
        if quiet_channel:
            highlights.append(f"Quietest Channel: #{quiet_channel.name} – {ch_curr[quiet_channel]}")
        if top_member[0]:
            highlights.append(f"Most Messages Sent: {top_member[0].display_name} – {top_member[1]}")
        if top_reactor[0]:
            highlights.append(f"Most Reactions Sent: {top_reactor[0].display_name} – {top_reactor[1]}")
        if longest_msg:
            highlights.append(f"Biggest Overthinker: {longest_msg.display_name} – {longest_len} chars")
        if bait_user:
            highlights.append(f"Best Engagement Bait: {bait_user.display_name} – {round(bait_ratio, 1)} reactions/msg")

        title_map = {
            "days": "Engagement Stats (Last 30 days)",
            "weeks": "Engagement Stats (Last 16 weeks)",
            "months": "Engagement Stats (Last 12 months)",
        }

        embed = discord.Embed(title=title_map[time_window], color=discord.Color.orange())
        embed.add_field(name="Metrics", value="\n".join(metrics), inline=False)
        if highlights:
            embed.add_field(name="Highlights", value="\n".join(highlights), inline=False)

        if chart and chart.value != "none":
            periods = sorted(stats["period_msgs"].keys())
            if chart.value == "messages":
                buf = self._messages_chart_png(stats["period_msgs"], periods, time_window)
            elif chart.value == "users":
                buf = self._users_chart_png(stats["period_active"], periods, time_window)
            elif chart.value == "channels":
                buf = self._channels_chart_png(ch_curr)
            file = discord.File(buf, filename="activity.png")
            embed.set_image(url="attachment://activity.png")
            try:
                await interaction.followup.send(embed=embed, file=file, ephemeral=True)
            except discord.HTTPException:
                if interaction.channel:
                    await interaction.channel.send(embed=embed, file=file)
        else:
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except discord.HTTPException:
                if interaction.channel:
                    await interaction.channel.send(embed=embed)

    @app_commands.command(name="engagement", description="Show recent guild engagement stats")
    @app_commands.describe(time_window="Time grouping", chart="Chart type")
    @app_commands.choices(
        time_window=[
            app_commands.Choice(name="Days", value="days"),
            app_commands.Choice(name="Weeks", value="weeks"),
            app_commands.Choice(name="Months", value="months"),
        ],
        chart=[
            app_commands.Choice(name="None", value="none"),
            app_commands.Choice(name="Messages", value="messages"),
            app_commands.Choice(name="Users", value="users"),
            app_commands.Choice(name="Channels", value="channels"),
        ],
    )
    async def engagement(
        self,
        interaction: discord.Interaction,
        time_window: str = "days",
        chart: app_commands.Choice[str] | None = None,
    ):
        log.info(
            "/engagement invoked by %s in %s",
            interaction.user.id,
            chan_name(interaction.channel),
        )
        await interaction.response.send_message("Working on it...", ephemeral=True)
        asyncio.create_task(self._engagement_background(interaction, time_window, chart))

async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))
