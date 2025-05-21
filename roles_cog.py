from __future__ import annotations
import os
from dotenv import load_dotenv
load_dotenv()

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Set

import discord
from discord.ext import commands, tasks

import bot_config as cfg  # pull ALL IDs / thresholds from here

# ─── Config aliases ─────────────────────────────────────────────────────────
GUILD_ID: int                    = cfg.GUILD_ID
DAILY_PING: int                  = cfg.DAILY_PING_CHANNEL
MONEY_TALK: int                  = cfg.MONEY_TALK_CHANNEL
BUILD_CHANNELS: Set[int]         = set(cfg.BUILD_CHANNELS)

ROLE_GHOST: int          = cfg.ROLE_GHOST
ROLE_THREADLORD: int     = cfg.ROLE_THREADLORD
ROLE_BUILDER: int        = cfg.ROLE_BUILDER
ROLE_PROMPT_WIZARD: int  = cfg.ROLE_PROMPT_WIZARD
ROLE_MONEY_GREMLIN: int  = cfg.ROLE_MONEY_GREMLIN
ROLE_CHAOS_MVP: int      = cfg.ROLE_CHAOS_MVP
ROLE_MASCOT: int         = cfg.ROLE_MASCOT

# thresholds (keep defaults but override in cfg if present)
INACTIVE_DAYS: int           = getattr(cfg, "INACTIVE_DAYS", 30)
THREADLORD_MIN_LEN: int      = getattr(cfg, "THREADLORD_MIN_LEN", 300)
THREADLORD_REQUIRED: int     = getattr(cfg, "THREADLORD_REQUIRED", 3)
PROMPT_WIZARD_WEEKLY: int    = getattr(cfg, "PROMPT_WIZARD_WEEKLY", 5)
MONEY_GREMLIN_WEEKLY: int    = getattr(cfg, "MONEY_GREMLIN_WEEKLY", 5)

# ─── Cog implementation ────────────────────────────────────────────────────
class RoleCog(commands.Cog):
    """Auto‑assigns social/behaviour roles based on activity patterns."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_activity: dict[int, datetime] = {}
        self.long_post_counts: defaultdict[int, int] = defaultdict(int)
        self.prompt_counts: defaultdict[int, int] = defaultdict(int)
        self.money_counts: defaultdict[int, int] = defaultdict(int)
        self.builder_flagged: set[int] = set()
        self.maintenance_loop.start()

    # ─── Listeners ───────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or msg.guild is None or msg.guild.id != GUILD_ID:
            return
        member_id = msg.author.id
        now = datetime.utcnow()
        self.last_activity[member_id] = now

        # Threadlord
        if len(msg.content) >= THREADLORD_MIN_LEN:
            self.long_post_counts[member_id] += 1
            if self.long_post_counts[member_id] >= THREADLORD_REQUIRED:
                await self._assign(msg.author, ROLE_THREADLORD)

        # Prompt Wizard (top‑level prompts only)
        if msg.channel.id == DAILY_PING and msg.reference is None:
            self.prompt_counts[member_id] += 1

        # Money Gremlin
        if msg.channel.id == MONEY_TALK:
            self.money_counts[member_id] += 1

        # Builder
        if msg.channel.id in BUILD_CHANNELS and (msg.attachments or "http" in msg.content):
            if member_id not in self.builder_flagged:
                await self._assign(msg.author, ROLE_BUILDER)
                self.builder_flagged.add(member_id)

    # ─── Background maintenance ──────────────────────────────────────────
    @tasks.loop(hours=24)
    async def maintenance_loop(self):
        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            return
        now = datetime.utcnow()

        for m in guild.members:
            if m.bot:
                continue
            last_seen = self.last_activity.get(m.id)
            if last_seen is None or (now - last_seen) > timedelta(days=INACTIVE_DAYS):
                await self._assign(m, ROLE_GHOST)
            else:
                await self._remove(m, ROLE_GHOST)

        # Monday reset (UTC)
        if now.weekday() == 0:
            self.long_post_counts.clear()
            self.builder_flagged.clear()
            # rotate weekly roles
            for m in guild.members:
                await self._remove(m, ROLE_PROMPT_WIZARD)
                await self._remove(m, ROLE_MONEY_GREMLIN)

            # award based on counts
            for uid, count in self.prompt_counts.items():
                if count >= PROMPT_WIZARD_WEEKLY:
                    member = guild.get_member(uid)
                    if member:
                        await self._assign(member, ROLE_PROMPT_WIZARD)
            for uid, count in self.money_counts.items():
                if count >= MONEY_GREMLIN_WEEKLY:
                    member = guild.get_member(uid)
                    if member:
                        await self._assign(member, ROLE_MONEY_GREMLIN)
            self.prompt_counts.clear()
            self.money_counts.clear()

    # ─── Admin commands ──────────────────────────────────────────────────
    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def chaos_mvp(self, ctx: commands.Context, member: discord.Member):
        """Grant Chaos MVP for 7 days."""
        await self._assign(member, ROLE_CHAOS_MVP)
        await ctx.send(f"{member.mention} crowned Chaos MVP for 7 days.")
        await asyncio.sleep(7 * 86400)
        await self._remove(member, ROLE_CHAOS_MVP)

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def mascot(self, ctx: commands.Context, member: discord.Member):
        """Rotate Server Mascot role (7‑day tenure)."""
        guild = ctx.guild
        for m in guild.members:
            if discord.utils.get(m.roles, id=ROLE_MASCOT):
                await self._remove(m, ROLE_MASCOT)
        await self._assign(member, ROLE_MASCOT)
        await ctx.send(f"{member.mention} is now the Server Mascot! 🎉")
        await asyncio.sleep(7 * 86400)
        await self._remove(member, ROLE_MASCOT)

    # ─── Role helpers ────────────────────────────────────────────────────
    async def _assign(self, member: discord.Member, role_id: int):
        role = member.guild.get_role(role_id)
        if role and role not in member.roles:
            await member.add_roles(role, reason="Auto‑assign by RoleCog")

    async def _remove(self, member: discord.Member, role_id: int):
        role = member.guild.get_role(role_id)
        if role and role in member.roles:
            await member.remove_roles(role, reason="Auto‑remove by RoleCog")

# ─── Loader ─────────────────────────────────────────────────────────────
async def setup(bot: commands.Bot):
    await bot.add_cog(RoleCog(bot))
