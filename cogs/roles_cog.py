"""Role automation for Gentlebot.
================================
Rotating engagement badges and inactivity flags.

Engagement badges: Top Poster, Certified Banger, Top Curator, First Drop,
The Summoner, Lore Creator, Reaction Engineer.

Inactivity flags: Ghost, Shadow, Lurker, NPC.

All IDs & thresholds come from **bot_config.py**.
"""
from __future__ import annotations
import logging
from collections import defaultdict, Counter
from datetime import datetime, timedelta, date

import pytz

import discord
from discord import app_commands
from discord.ext import commands, tasks

from util import chan_name

log = logging.getLogger(__name__)

import bot_config as cfg

# ── Behavioral Role Config ──────────────────────────────────────────────────
GUILD_ID: int = cfg.GUILD_ID

ROLE_GHOST: int = cfg.ROLE_GHOST
ROLE_TOP_POSTER: int = cfg.ROLE_TOP_POSTER
ROLE_CERTIFIED_BANGER: int = cfg.ROLE_CERTIFIED_BANGER
ROLE_TOP_CURATOR: int = cfg.ROLE_TOP_CURATOR
ROLE_FIRST_DROP: int = cfg.ROLE_FIRST_DROP
ROLE_SUMMONER: int = cfg.ROLE_SUMMONER
ROLE_LORE_CREATOR: int = cfg.ROLE_LORE_CREATOR
ROLE_REACTION_ENGINEER: int = cfg.ROLE_REACTION_ENGINEER
ROLE_SHADOW_FLAG: int = cfg.ROLE_SHADOW_FLAG
ROLE_LURKER_FLAG: int = cfg.ROLE_LURKER_FLAG
ROLE_NPC_FLAG: int = cfg.ROLE_NPC_FLAG

# thresholds (override in bot_config if desired)
INACTIVE_DAYS: int = cfg.INACTIVE_DAYS
LA = pytz.timezone("America/Los_Angeles")

class RoleCog(commands.Cog):
    """Assigns engagement badges and inactivity flags."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # engagement/inactivity tracking
        self.messages: list[dict] = []
        self.reactions: list[dict] = []
        self.last_online: defaultdict[int, datetime] = defaultdict(lambda: datetime.utcnow())
        self.first_drop_day: date | None = None
        self.first_drop_user: int | None = None
        self.badge_task.start()

    @app_commands.command(name="refreshroles", description="Force badge and flag updates")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def refresh_roles(self, interaction: discord.Interaction):
        """Admins can manually trigger the role rotation."""
        log.info("/refreshroles invoked by %s in %s", interaction.user.id, chan_name(interaction.channel))
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await self.badge_task()
        except Exception as exc:
            log.exception("refreshroles failed: %s", exc)
            await interaction.followup.send(
                "Failed to refresh roles.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "Role rotation complete.", ephemeral=True
            )

    async def _get_member(self, guild: discord.Guild, user_id: int) -> discord.Member | None:
        """Return a member from cache or fetch if missing."""
        member = guild.get_member(user_id)
        if member:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound:
            log.warning("Member %s not found in guild %s", user_id, guild.id)
        except discord.HTTPException as exc:
            log.error("Failed to fetch member %s: %s", user_id, exc)
        return None

    # -- Activity listeners --
    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.guild.id != GUILD_ID:
            return
        if after.status != discord.Status.offline:
            self.last_online[after.id] = datetime.utcnow()

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or msg.guild is None or msg.guild.id != GUILD_ID:
            return
        member_id = msg.author.id
        self.last_online[member_id] = datetime.utcnow()
        info = {
            "id": msg.id,
            "author": member_id,
            "ts": msg.created_at,
            "len": len(msg.content),
            "rich": bool(msg.attachments) or bool(msg.embeds) or ("http" in msg.content),
            "mentions": msg.content.count("@here") + msg.content.count("@everyone"),
            "reply_to": msg.reference.resolved.author.id if msg.reference and msg.reference.resolved else None,
        }
        self.messages.append(info)
        la_now = datetime.now(tz=LA)
        if self.first_drop_day != la_now.date():
            self.first_drop_day = la_now.date()
            self.first_drop_user = member_id
            await self._rotate_single(msg.guild, ROLE_FIRST_DROP, member_id)


    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if reaction.message.guild is None or reaction.message.guild.id != GUILD_ID:
            return
        if user.bot:
            return
        self.last_online[user.id] = datetime.utcnow()
        creator = None
        if isinstance(reaction.emoji, discord.Emoji):
            em = reaction.message.guild.get_emoji(reaction.emoji.id)
            if em and em.user:
                creator = em.user.id
        entry = {
            "ts": datetime.utcnow(),
            "msg": reaction.message.id,
            "msg_author": reaction.message.author.id,
            "emoji": str(reaction.emoji),
            "creator": creator,
            "user": user.id,
        }
        self.reactions.append(entry)

    # ── Badge Helpers ─────────────────────────────────────────────────────
    async def _rotate_single(self, guild: discord.Guild, role_id: int, user_id: int | None):
        role = guild.get_role(role_id)
        if not role:
            return
        for m in guild.members:
            if role in m.roles and m.id != user_id:
                try:
                    await m.remove_roles(role, reason="badge rotation")
                except Exception:
                    pass
        if user_id:
            target = guild.get_member(user_id)
            if target and role not in target.roles:
                try:
                    await target.add_roles(role, reason="badge rotation")
                except Exception:
                    pass

    async def _assign_flag(self, guild: discord.Guild, member: discord.Member, role_id: int):
        for r in (ROLE_GHOST, ROLE_SHADOW_FLAG, ROLE_LURKER_FLAG, ROLE_NPC_FLAG):
            if r == 0:
                continue
            role = guild.get_role(r)
            if role and role in member.roles and r != role_id:
                try:
                    await member.remove_roles(role, reason="flag update")
                except Exception:
                    pass
        role = guild.get_role(role_id)
        if role and role_id and role not in member.roles:
            try:
                await member.add_roles(role, reason="flag update")
            except Exception:
                pass

    # ── Badge Rotation Task ─────────────────────────────────────────────
    @tasks.loop(hours=24)
    async def badge_task(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return
        now = datetime.utcnow()
        cutoff14 = now - timedelta(days=14)
        cutoff30 = now - timedelta(days=30)
        self.messages = [m for m in self.messages if m["ts"] >= cutoff30]
        self.reactions = [r for r in self.reactions if r["ts"] >= cutoff30]

        counts = Counter(m["author"] for m in self.messages if m["ts"] >= cutoff14)
        top_poster = counts.most_common(1)[0][0] if counts else None
        await self._rotate_single(guild, ROLE_TOP_POSTER, top_poster)

        msg_counts = Counter()
        laugh_counts = Counter()
        for m in self.messages:
            if m["ts"] >= cutoff14:
                msg_counts[m["author"]] += 1
        for r in self.reactions:
            if r["ts"] >= cutoff14 and r["emoji"] in ("😂", "😆", "👍", "🤣"):
                laugh_counts[r["msg_author"]] += 1
        best = None
        best_avg = 0.0
        for uid, cnt in msg_counts.items():
            if cnt >= 10:
                avg = laugh_counts[uid] / cnt
                if avg > best_avg:
                    best_avg = avg
                    best = uid
        await self._rotate_single(guild, ROLE_CERTIFIED_BANGER, best)

        reaction_map = Counter()
        for r in self.reactions:
            if r["ts"] >= cutoff14:
                reaction_map[r["msg"]] += 1
        curator = Counter()
        for m in self.messages:
            if m["ts"] >= cutoff14 and m["rich"] and reaction_map[m["id"]] >= 3:
                curator[m["author"]] += 1
        top_curator = curator.most_common(1)[0][0] if curator else None
        await self._rotate_single(guild, ROLE_TOP_CURATOR, top_curator)

        await self._rotate_single(guild, ROLE_FIRST_DROP, self.first_drop_user)

        summons = Counter(m["author"] for m in self.messages if m["ts"] >= cutoff30 for _ in range(m["mentions"]))
        summoner = summons.most_common(1)[0][0] if summons else None
        await self._rotate_single(guild, ROLE_SUMMONER, summoner)

        referenced = Counter(m["reply_to"] for m in self.messages if m["ts"] >= cutoff30 and m["reply_to"])
        lore_creator = referenced.most_common(1)[0][0] if referenced else None
        await self._rotate_single(guild, ROLE_LORE_CREATOR, lore_creator)

        creator_counts = Counter(r["creator"] for r in self.reactions if r["ts"] >= cutoff30 and r["creator"])
        reaction_engineer = creator_counts.most_common(1)[0][0] if creator_counts else None
        await self._rotate_single(guild, ROLE_REACTION_ENGINEER, reaction_engineer)

        msg_count14 = Counter(m["author"] for m in self.messages if m["ts"] >= cutoff14)
        react_count14 = Counter(r["user"] for r in self.reactions if r["ts"] >= cutoff14)
        long_msgs30 = defaultdict(int)
        rich_msgs30 = defaultdict(int)
        for m in self.messages:
            if m["ts"] >= cutoff30:
                if m["len"] > 150:
                    long_msgs30[m["author"]] += 1
                if m["rich"]:
                    rich_msgs30[m["author"]] += 1
        for member in guild.members:
            if member.bot:
                continue
            last = self.last_online.get(member.id, datetime.utcfromtimestamp(0))
            if now - last > timedelta(days=14):
                await self._assign_flag(guild, member, ROLE_GHOST)
                continue
            if msg_count14[member.id] == 0 and react_count14[member.id] == 0:
                await self._assign_flag(guild, member, ROLE_SHADOW_FLAG)
                continue
            if msg_count14[member.id] < 4 and react_count14[member.id] >= 1:
                await self._assign_flag(guild, member, ROLE_LURKER_FLAG)
                continue
            if now - last <= timedelta(days=30) and long_msgs30[member.id] == 0 and rich_msgs30[member.id] == 0:
                await self._assign_flag(guild, member, ROLE_NPC_FLAG)
                continue
            await self._assign_flag(guild, member, 0)

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
            log.debug("Member %s missing role %s on remove; fetching", member.id, role_id)
            try:
                refreshed = await member.guild.fetch_member(member.id)
            except discord.NotFound:
                log.warning("Member %s disappeared while removing role %s", member.id, role_id)
                return
            except discord.HTTPException as exc:
                log.error("Failed to refresh member %s: %s", member.id, exc)
                return
            if role not in refreshed.roles:
                log.info("Member %s no longer has role %s", member.id, role_id)
                return
            member = refreshed
        try:
            await member.remove_roles(role, reason="RoleCog auto-remove")
            log.info("Successfully removed role %s (%s) from member %s", role.name, role_id, member.id)
        except Exception as e:
            log.error("Failed removing role %s from %s: %s", role_id, member.id, e)

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleCog(bot))
