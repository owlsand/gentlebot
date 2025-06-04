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
            self.bot.tree.add_command(self.engagement)
            await self.bot.tree.sync(guild=discord.Object(id=cfg.GUILD_ID))
            log.info("StatsCog slash command synced")
        except Exception as e:
            log.exception("Failed to sync StatsCog commands: %s", e)

    async def _gather_stats(self, days: int = 7, per_channel: int = 1000):
        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            return None, None, None, None
        after = datetime.utcnow() - timedelta(days=days)
        user_counts: defaultdict[discord.Member, int] = defaultdict(int)
        channel_counts: defaultdict[discord.TextChannel, int] = defaultdict(int)
        daily_messages: defaultdict[datetime.date, int] = defaultdict(int)
        daily_users: defaultdict[datetime.date, set[int]] = defaultdict(set)
        for channel in guild.text_channels:
            try:
                async for msg in channel.history(limit=per_channel, after=after):
                    if msg.author.bot:
                        continue
                    user_counts[msg.author] += 1
                    channel_counts[channel] += 1
                    day = msg.created_at.date()
                    daily_messages[day] += 1
                    daily_users[day].add(msg.author.id)
            except Exception as e:
                log.exception("History fetch failed for channel %s: %s", channel.id, e)
        daily_active = {d: len(u) for d, u in daily_users.items()}
        return user_counts, channel_counts, daily_messages, daily_active

    def _chart_png(self, msgs: dict[datetime.date, int], active: dict[datetime.date, int]) -> io.BytesIO:
        dates = sorted(msgs)
        msg_counts = [msgs[d] for d in dates]
        user_counts = [active.get(d, 0) for d in dates]
        plt.style.use("seaborn-v0_8-whitegrid")
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.plot(dates, msg_counts, label="Messages", color="#2081C3", linewidth=1.6)
        ax.plot(dates, user_counts, label="Users", color="#E66100", linewidth=1.6)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        ax.tick_params(labelsize=7)
        ax.legend(fontsize=7)
        ax.set_title("Activity by Day", fontsize=9)
        fig.tight_layout(pad=1.0)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        buf.seek(0)
        return buf

    @app_commands.command(name="engagement", description="Show recent guild engagement stats")
    @app_commands.describe(days="Days to analyze (1-30)", chart="Include activity chart")
    async def engagement(self, interaction: discord.Interaction, days: app_commands.Range[int, 1, 30] = 7, chart: bool = False):
        log.info("/engagement invoked by %s in %s", interaction.user.id, getattr(interaction.channel, "name", interaction.channel_id))
        await interaction.response.defer(thinking=True, ephemeral=True)
        user_counts, channel_counts, daily_messages, daily_active = await self._gather_stats(days)
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
        if chart:
            buf = self._chart_png(daily_messages, daily_active)
            file = discord.File(buf, filename="activity.png")
            embed.set_image(url="attachment://activity.png")
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))
