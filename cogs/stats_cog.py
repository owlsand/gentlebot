from __future__ import annotations
import logging
from collections import defaultdict
from datetime import datetime, timedelta
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import discord
from discord import app_commands
from discord.ext import commands

import bot_config as cfg

log = logging.getLogger(__name__)

class StatsCog(commands.Cog):
    """Slash command to show recent message activity stats."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.bot.tree.sync()
            log.info("Slash commands synced on ready.")
        except Exception as e:
            log.exception("Failed to sync commands: %s", e)

    async def _gather_stats(self, days: int = 30, per_channel: int = 1000):
        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            return None, None, None, None
        after = datetime.utcnow() - timedelta(days=days)
        user_counts: defaultdict[discord.Member, int] = defaultdict(int)
        channel_counts: defaultdict[discord.TextChannel, int] = defaultdict(int)
        daily_user_msgs: defaultdict[datetime.date, defaultdict[discord.Member, int]] = defaultdict(lambda: defaultdict(int))
        daily_users: defaultdict[datetime.date, set[int]] = defaultdict(set)
        for channel in guild.text_channels:
            try:
                async for msg in channel.history(limit=per_channel, after=after):
                    user_counts[msg.author] += 1
                    channel_counts[channel] += 1
                    day = msg.created_at.date()
                    daily_user_msgs[day][msg.author] += 1
                    daily_users[day].add(msg.author.id)
            except Exception as e:
                log.exception("History fetch failed for channel %s: %s", channel.id, e)
        daily_active = {d: len(u) for d, u in daily_users.items()}
        return user_counts, channel_counts, daily_user_msgs, daily_active

    def _messages_chart_png(
        self, daily_user_msgs: dict[datetime.date, dict[discord.Member, int]], days: int
    ) -> io.BytesIO:
        """Stacked bar chart of daily message counts grouped by user."""
        end = datetime.utcnow().date()
        start = end - timedelta(days=days - 1)
        dates = [start + timedelta(days=i) for i in range(days)]
        # Determine top contributors overall
        totals: defaultdict[discord.Member, int] = defaultdict(int)
        for day_counts in daily_user_msgs.values():
            for user, cnt in day_counts.items():
                totals[user] += cnt
        top_users = [u for u, _ in sorted(totals.items(), key=lambda x: x[1], reverse=True)[:5]]

        plt.style.use("seaborn-v0_8-darkgrid")
        fig, ax = plt.subplots(figsize=(7, 3.5))
        colors = plt.get_cmap("tab10").colors
        bottom = [0] * len(dates)
        for idx, user in enumerate(top_users):
            vals = [daily_user_msgs.get(d, {}).get(user, 0) for d in dates]
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
            total = sum(daily_user_msgs[d].values())
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

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        ax.tick_params(labelsize=8)
        ax.legend(fontsize=8, ncol=2, loc="upper left")
        ax.set_title("Messages by Day", fontsize=10)
        fig.tight_layout(pad=1.0)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        buf.seek(0)
        return buf

    def _users_chart_png(self, daily_active: dict[datetime.date, int], days: int) -> io.BytesIO:
        """Bar chart of daily active user counts."""
        end = datetime.utcnow().date()
        start = end - timedelta(days=days - 1)
        dates = [start + timedelta(days=i) for i in range(days)]
        counts = [daily_active.get(d, 0) for d in dates]
        plt.style.use("seaborn-v0_8-darkgrid")
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.bar(dates, counts, color="#007acc", edgecolor="white", linewidth=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        ax.tick_params(labelsize=8)
        ax.set_title("Active Users by Day", fontsize=10)
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
        plt.style.use("seaborn-v0_8-darkgrid")
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

    @app_commands.command(name="engagement", description="Show recent guild engagement stats")
    @app_commands.describe(days="Days to analyze (1-30)", chart="Chart type")
    @app_commands.choices(
        chart=[
            app_commands.Choice(name="None", value="none"),
            app_commands.Choice(name="Messages", value="messages"),
            app_commands.Choice(name="Users", value="users"),
            app_commands.Choice(name="Channels", value="channels"),
        ]
    )
    async def engagement(
        self,
        interaction: discord.Interaction,
        days: app_commands.Range[int, 1, 30] = 30,
        chart: app_commands.Choice[str] | None = None,
    ):
        log.info("/engagement invoked by %s in %s", interaction.user.id, getattr(interaction.channel, "name", interaction.channel_id))
        await interaction.response.defer(thinking=True, ephemeral=True)
        user_counts, channel_counts, daily_msgs, daily_active = await self._gather_stats(days)
        if user_counts is None:
            await interaction.followup.send("Guild not found.", ephemeral=True)
            return
        if not user_counts:
            await interaction.followup.send("No recent activity found.", ephemeral=True)
            return
        top_members = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_channels = sorted(channel_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        embed = discord.Embed(title=f"Engagement Stats – last {days} days", color=discord.Color.orange())
        embed.add_field(name="Top Members", value="\n".join(f"{i+1}. {m.display_name} – {c}" for i, (m, c) in enumerate(top_members)), inline=False)
        embed.add_field(name="Top Channels", value="\n".join(f"{i+1}. #{ch.name} – {c}" for i, (ch, c) in enumerate(top_channels)), inline=False)
        if chart and chart.value != "none":
            if chart.value == "messages":
                buf = self._messages_chart_png(daily_msgs, days)
            elif chart.value == "users":
                buf = self._users_chart_png(daily_active, days)
            elif chart.value == "channels":
                buf = self._channels_chart_png(channel_counts)
            file = discord.File(buf, filename="activity.png")
            embed.set_image(url="attachment://activity.png")
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))
