"""
roles_cog.py – Behavior and Vanity Role Automation for Gentlebot
================================================================
Handles both reaction-based vanity roles and activity-based behavioral roles:

Vanity Roles (single-choice)
  🔥 Team Chaos
  ☕️ Team Cozy
  👀 Shadow Council
  🧌 Team Goblin
  📜 Team Sage
  📢 Team Hype

Behavioral Roles (auto-assigned):
  • Ghost           – no posts in X days
  • Threadlord      – ≥N long messages per period
  • Builder         – first attachment/link in build channels
  • Prompt Wizard   – top-level prompts count in DAILY_PING
  • Money Gremlin   – message count in MONEY_TALK

Admin Commands:
  • !chaos_mvp @user – grant Chaos MVP for 7 days
  • !mascot @user    – rotate Server Mascot for 7 days

All IDs & thresholds come from **bot_config.py**.
"""
from __future__ import annotations
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Set, Dict

import discord
from discord.ext import commands, tasks
from util import chan_name

log = logging.getLogger(__name__)

import bot_config as cfg

# ── Vanity Role Config ──────────────────────────────────────────────────────
VANITY_CHANNEL: int = getattr(cfg, 'VANITY_CHANNEL', None)
VANITY_MESSAGE_ID: int = getattr(cfg, 'VANITY_MESSAGE', None)
VANITY_ROLES: Dict[str, int] = {
    '🔥': cfg.ROLE_CHAOS,
    '☕️': cfg.ROLE_COZY,
    '👀': cfg.ROLE_SHADOW,
    '🃏': cfg.ROLE_GOBLIN,
    '🌿': cfg.ROLE_SAGE,
    '📢': cfg.ROLE_HYPE,
}

# ── Behavioral Role Config ──────────────────────────────────────────────────
GUILD_ID: int = cfg.GUILD_ID
DAILY_PING: int = cfg.DAILY_PING_CHANNEL
MONEY_TALK: int = cfg.MONEY_TALK_CHANNEL
BUILD_CHANNELS: Set[int] = set(cfg.BUILD_CHANNELS)

ROLE_GHOST: int = cfg.ROLE_GHOST
ROLE_THREADLORD: int = cfg.ROLE_THREADLORD
ROLE_BUILDER: int = cfg.ROLE_BUILDER
ROLE_PROMPT_WIZARD: int = cfg.ROLE_PROMPT_WIZARD
ROLE_MONEY_GREMLIN: int = cfg.ROLE_MONEY_GREMLIN
ROLE_CHAOS_MVP: int = cfg.ROLE_CHAOS_MVP
ROLE_MASCOT: int = cfg.ROLE_MASCOT

# thresholds (override in bot_config if desired)
INACTIVE_DAYS: int = cfg.INACTIVE_DAYS
THREADLORD_MIN_LEN: int = cfg.THREADLORD_MIN_LEN
THREADLORD_REQUIRED: int = cfg.THREADLORD_REQUIRED
PROMPT_WIZARD_WEEKLY: int = cfg.PROMPT_WIZARD_WEEKLY
MONEY_GREMLIN_WEEKLY: int = cfg.MONEY_GREMLIN_WEEKLY

class RoleCog(commands.Cog):
    """Manages vanity reaction roles and auto-assigns behavioral roles based on activity."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Debug: log configured vanity channel and message
        self.last_activity: dict[int, datetime] = {}
        self.long_post_counts: defaultdict[int, int] = defaultdict(int)
        self.prompt_counts: defaultdict[int, int] = defaultdict(int)
        self.money_counts: defaultdict[int, int] = defaultdict(int)
        self.builder_flagged: Set[int] = set()
        self.minute_maintenance.start()
        self.daily_maintenance.start()

    # ── Vanity Reaction Handlers ───────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id != GUILD_ID or payload.message_id != VANITY_MESSAGE_ID:
            return
        emoji = str(payload.emoji)
        if emoji not in VANITY_ROLES:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        if not member:
            return
        for em, rid in VANITY_ROLES.items():
            if rid != VANITY_ROLES[emoji] and rid in [r.id for r in member.roles]:
                await self._remove(member, rid)
        role_id = VANITY_ROLES[emoji]
        log.info("Attempting vanity assign role_id=%s for emoji %s to member %s", role_id, emoji, member.id)
        await self._assign(member, role_id)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id != GUILD_ID or payload.message_id != VANITY_MESSAGE_ID:
            return
        emoji = str(payload.emoji)
        if emoji not in VANITY_ROLES:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        if not member:
            return
        await self._remove(member, VANITY_ROLES[emoji])

        # ── Activity Listeners ─────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or msg.guild is None or msg.guild.id != GUILD_ID:
            return
        member_id = msg.author.id
        now = datetime.utcnow()
        self.last_activity[member_id] = now
        # Immediately remove Ghost role when user becomes active
        await self._remove(msg.author, ROLE_GHOST)

        # Threadlord: long messages
        if len(msg.content) >= THREADLORD_MIN_LEN:
            self.long_post_counts[member_id] += 1
            if self.long_post_counts[member_id] >= THREADLORD_REQUIRED:
                await self._assign(msg.author, ROLE_THREADLORD)

        # Prompt Wizard: top-level prompts in DAILY_PING
        if msg.channel.id == DAILY_PING and msg.reference is None:
            self.prompt_counts[member_id] += 1
            # Auto-assign when threshold reached
            if self.prompt_counts[member_id] >= PROMPT_WIZARD_WEEKLY:
                await self._assign(msg.author, ROLE_PROMPT_WIZARD)

        # Money Gremlin: any msg in MONEY_TALK
        if msg.channel.id == MONEY_TALK:
            self.money_counts[member_id] += 1
            # Auto-assign when threshold reached
            if self.money_counts[member_id] >= MONEY_GREMLIN_WEEKLY:
                await self._assign(msg.author, ROLE_MONEY_GREMLIN)

        # Builder: attachments or links in BUILD_CHANNELS
        if msg.channel.id in BUILD_CHANNELS and (msg.attachments or "http" in msg.content):
            if member_id not in self.builder_flagged:
                await self._assign(msg.author, ROLE_BUILDER)
                self.builder_flagged.add(member_id)

    # ── Background Maintenance ─────────────────────────────────────────────────
    @tasks.loop(minutes=1)
    async def minute_maintenance(self):
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return
        now = datetime.utcnow()
        # Ghost role still managed daily
        for member in guild.members:
            if member.bot:
                continue
            last = self.last_activity.get(member.id)
            if last is None or (now - last) > timedelta(days=INACTIVE_DAYS):
                await self._assign(member, ROLE_GHOST)
            else:
                await self._remove(member, ROLE_GHOST)
        # Weekly reset on Mondays (UTC)
        if now.weekday() == 0:
            self.long_post_counts.clear()
            self.builder_flagged.clear()
            self.prompt_counts.clear()
            self.money_counts.clear()

    @tasks.loop(hours=24)
    async def daily_maintenance(self):
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return
        now = datetime.utcnow()
        for member in guild.members:
            if member.bot:
                continue
            last = self.last_activity.get(member.id)
            if last is None or (now - last) > timedelta(days=INACTIVE_DAYS):
                await self._assign(member, ROLE_GHOST)
            else:
                await self._remove(member, ROLE_GHOST)
        if now.weekday() == 0:
            self.long_post_counts.clear()
            self.builder_flagged.clear()
            for uid, count in self.prompt_counts.items():
                if count >= PROMPT_WIZARD_WEEKLY:
                    m = guild.get_member(uid)
                    if m:
                        await self._assign(m, ROLE_PROMPT_WIZARD)
            for uid, count in self.money_counts.items():
                if count >= MONEY_GREMLIN_WEEKLY:
                    m = guild.get_member(uid)
                    if m:
                        await self._assign(m, ROLE_MONEY_GREMLIN)
            self.prompt_counts.clear()
            self.money_counts.clear()

    # ── Admin Commands ─────────────────────────────────────────────────────────
    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def chaos_mvp(self, ctx: commands.Context, member: discord.Member):
        log.info("!chaos_mvp invoked by %s in %s for target %s", ctx.author.id, chan_name(ctx.channel), member.id)
        await self._assign(member, ROLE_CHAOS_MVP)
        await ctx.send(f"{member.mention} crowned Chaos MVP for 7 days.")
        await asyncio.sleep(7 * 86400)
        await self._remove(member, ROLE_CHAOS_MVP)

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def mascot(self, ctx: commands.Context, member: discord.Member):
        log.info("!mascot invoked by %s in %s for target %s", ctx.author.id, chan_name(ctx.channel), member.id)
        guild = ctx.guild
        for m in guild.members:
            if discord.utils.get(m.roles, id=ROLE_MASCOT):
                await self._remove(m, ROLE_MASCOT)
        await self._assign(member, ROLE_MASCOT)
        await ctx.send(f"{member.mention} is now the Server Mascot! 🎉")
        await asyncio.sleep(7 * 86400)
        await self._remove(member, ROLE_MASCOT)

    # ── Internal Role Helpers ──────────────────────────────────────────────────
    async def _assign(self, member: discord.Member, role_id: int):
        log.info("Attempting to assign new role (%s) to member (%s)", role_id, member.id)
        role = member.guild.get_role(role_id)
        if not role:
            log.error("ERROR - role_id=%s not found in guild %s", role_id, member.guild.id)
            return
        if role in member.roles:
            log.info("Member %s already has role %s", member.id, role_id)
            return
        try:
            await member.add_roles(role, reason="RoleCog auto-assign")
            log.info("Successfully assigned role %s (%s) to member %s", role.name, role_id, member.id)
        except Exception as e:
            log.error("Failed assigning role %s to %s: %s", role_id, member.id, e)

    async def _remove(self, member: discord.Member, role_id: int):
        role = member.guild.get_role(role_id)
        if not role:
            log.error("ERROR - role_id=%s not found in guild %s", role_id, member.guild.id)
            return
        if role not in member.roles:
            return
        try:
            await member.remove_roles(role, reason="RoleCog auto-remove")
            log.info("Successfully removed role %s (%s) from member %s", role.name, role_id, member.id)
        except Exception as e:
            log.error("Failed removing role %s from %s: %s", role_id, member.id, e)

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleCog(bot))
