"""Role automation for Gentlebot.
================================
Rotating engagement badges and inactivity flags.

Roles are refreshed automatically on startup so a redeploy won't reset
any of the vanity badges or inactivity flags.

Engagement badges: Top Poster, Certified Banger, Top Curator, Early Bird,
The Summoner, Lore Creator, Reaction Engineer, Galaxy Brain, Wordsmith,
Sniper, Night Owl, Comeback Kid, Ghostbuster.

Inactivity flags:
  - **Ghost** – no presence events recorded in the last 7 days
  - **Lurker** – no messages in the last 7 days but at least one recent presence event
  - **NPC** – 1–5 messages sent in the last 7 days

All IDs & thresholds come from **bot_config.py**.
"""
from __future__ import annotations
import logging
from collections import defaultdict, Counter
from datetime import datetime, timedelta, date, timezone

import pytz

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..tasks.daily_digest import assign_tiers
from ..db import get_pool

from ..util import chan_name, user_name, guild_name
from .. import bot_config as cfg

# Use a hierarchical logger so messages propagate to the main gentlebot logger
log = logging.getLogger(f"gentlebot.{__name__}")

# ── Behavioral Role Config ──────────────────────────────────────────────────
GUILD_ID: int = cfg.GUILD_ID

ROLE_GHOST: int = cfg.ROLE_GHOST
ROLE_TOP_POSTER: int = cfg.ROLE_TOP_POSTER
ROLE_CERTIFIED_BANGER: int = cfg.ROLE_CERTIFIED_BANGER
ROLE_TOP_CURATOR: int = cfg.ROLE_TOP_CURATOR
ROLE_EARLY_BIRD: int = cfg.ROLE_EARLY_BIRD
ROLE_SUMMONER: int = cfg.ROLE_SUMMONER
ROLE_LORE_CREATOR: int = cfg.ROLE_LORE_CREATOR
ROLE_REACTION_ENGINEER: int = cfg.ROLE_REACTION_ENGINEER
ROLE_GALAXY_BRAIN: int = cfg.ROLE_GALAXY_BRAIN
ROLE_WORDSMITH: int = cfg.ROLE_WORDSMITH
ROLE_SNIPER: int = cfg.ROLE_SNIPER
ROLE_NIGHT_OWL: int = cfg.ROLE_NIGHT_OWL
ROLE_COMEBACK_KID: int = cfg.ROLE_COMEBACK_KID
ROLE_GHOSTBUSTER: int = cfg.ROLE_GHOSTBUSTER
ROLE_SHADOW_FLAG: int = cfg.ROLE_SHADOW_FLAG
ROLE_LURKER_FLAG: int = cfg.ROLE_LURKER_FLAG
ROLE_NPC_FLAG: int = cfg.ROLE_NPC_FLAG

# thresholds (override in bot_config if desired)
INACTIVE_DAYS: int = cfg.INACTIVE_DAYS
# Use Pacific time for daily role rotations
LA = pytz.timezone("America/Los_Angeles")

class RoleCog(commands.Cog):
    """Assigns engagement badges and inactivity flags."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # engagement/inactivity tracking
        self.messages: list[dict] = []
        self.reactions: list[dict] = []
        self.last_online: defaultdict[int, datetime] = defaultdict(discord.utils.utcnow)
        self.last_message_ts: datetime = discord.utils.utcnow()
        self.last_presence: dict[int, datetime] = {}
        self.assign_counts: Counter[int] = Counter()
        self._startup_refreshed: bool = False
        self._presence_fetch_enabled: bool = True
        self.badge_task.start()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self._startup_refreshed:
            await self._fetch_recent_activity()
            await self.badge_task()
            self._startup_refreshed = True

    @app_commands.command(name="refreshroles", description="Fetch history and rotate badges")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def refresh_roles(self, interaction: discord.Interaction):
        """Admins can manually trigger the role rotation.

        This fetches the last 14 days of guild history so badges and flags are
        computed even after a restart.
        """
        log.info(
            "/refreshroles invoked by %s in %s",
            user_name(interaction.user),
            chan_name(interaction.channel),
        )
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await self._fetch_recent_activity()
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
            user = self.bot.get_user(user_id)
            log.warning(
                "Member %s not found in guild %s",
                user_name(user),
                guild_name(guild),
            )
        except discord.HTTPException as exc:
            user = self.bot.get_user(user_id)
            log.error(
                "Failed to fetch member %s: %s",
                user_name(user),
                exc,
            )
        return None

    async def _fetch_recent_activity(self, days: int = 14) -> None:
        """Populate message and reaction caches from recent guild history."""
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return

        now = discord.utils.utcnow()
        cutoff = now - timedelta(days=days)
        self.messages.clear()
        self.reactions.clear()
        self.last_online.clear()
        self.last_presence.clear()
        await self._refresh_presence_from_archive(now)

        for channel in guild.text_channels:
            try:
                async for msg in channel.history(limit=None, after=cutoff):
                    if msg.author.bot:
                        continue
                    self.last_online[msg.author.id] = max(
                        self.last_online.get(msg.author.id, cutoff), msg.created_at
                    )
                    self.last_presence[msg.author.id] = max(
                        self.last_presence.get(msg.author.id, cutoff), msg.created_at
                    )
                    info = {
                        "id": msg.id,
                        "author": msg.author.id,
                        "ts": msg.created_at,
                        "len": len(msg.content),
                        "words": len(msg.content.split()),
                        "rich": bool(msg.attachments)
                        or bool(msg.embeds)
                        or ("http" in msg.content),
                        "mentions": msg.content.count("@here")
                        + msg.content.count("@everyone"),
                        "mention_ids": [u.id for u in msg.mentions],
                        "reply_to": msg.reference.resolved.author.id
                        if msg.reference and msg.reference.resolved
                        else None,
                    }
                    self.messages.append(info)

                    for reaction in msg.reactions:
                        try:
                            users = [u async for u in reaction.users(limit=None)]
                        except Exception as exc:
                            log.exception(
                                "Reaction fetch failed for %s on %s: %s",
                                reaction.emoji,
                                msg.id,
                                exc,
                            )
                            continue
                        for user in users:
                            if user.bot:
                                continue
                            self.last_online[user.id] = max(
                                self.last_online.get(user.id, cutoff), msg.created_at
                            )
                            self.last_presence[user.id] = max(
                                self.last_presence.get(user.id, cutoff), msg.created_at
                            )
                            creator = None
                            if isinstance(reaction.emoji, discord.Emoji):
                                em = guild.get_emoji(reaction.emoji.id)
                                if em and em.user:
                                    creator = em.user.id
                            self.reactions.append(
                                {
                                    "ts": msg.created_at,
                                    "msg": msg.id,
                                    "msg_author": msg.author.id,
                                    "emoji": str(reaction.emoji),
                                    "creator": creator,
                                    "user": user.id,
                                }
                            )
            except discord.Forbidden as exc:
                log.warning(
                    "History fetch failed for channel %s: %s",
                    chan_name(channel),
                    exc,
                )
            except Exception as exc:
                log.exception(
                    "History fetch failed for channel %s: %s",
                    chan_name(channel),
                    exc,
                )

        if self.messages:
            self.last_message_ts = max(m["ts"] for m in self.messages)

    async def _refresh_presence_from_archive(self, now: datetime) -> None:
        """Backfill recent presence data from the archival Postgres store."""
        if not self._presence_fetch_enabled:
            return
        try:
            pool = await get_pool()
        except RuntimeError:
            self._presence_fetch_enabled = False
            log.info("Presence archive unavailable; skipping presence backfill")
            return
        except Exception as exc:  # pragma: no cover - defensive logging
            log.exception("Failed to obtain Postgres pool for presence refresh: %s", exc)
            return

        cutoff = now - timedelta(days=7)
        try:
            rows = await pool.fetch(
                """
                SELECT user_id, MAX(event_at) AS last_event
                FROM discord.presence_update
                WHERE guild_id=$1 AND event_at >= $2 AND status <> 'offline'
                GROUP BY user_id
                """,
                GUILD_ID,
                cutoff,
            )
        except Exception as exc:
            log.exception("Failed to query archived presence events: %s", exc)
            return

        for uid, ts in list(self.last_presence.items()):
            if ts < cutoff:
                self.last_presence.pop(uid)

        for row in rows:
            user_id = row["user_id"]
            event_at = row["last_event"]
            if event_at is None:
                continue
            if event_at.tzinfo is None:
                event_at = event_at.replace(tzinfo=timezone.utc)
            existing_presence = self.last_presence.get(user_id)
            if existing_presence is None or event_at > existing_presence:
                self.last_presence[user_id] = event_at
            existing_online = self.last_online.get(user_id)
            if existing_online is None or event_at > existing_online:
                self.last_online[user_id] = event_at

    # -- Activity listeners --
    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.guild.id != GUILD_ID:
            return
        if after.status != discord.Status.offline:
            now = discord.utils.utcnow()
            self.last_online[after.id] = now
            self.last_presence[after.id] = now

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or msg.guild is None or msg.guild.id != GUILD_ID:
            return
        member_id = msg.author.id
        now = discord.utils.utcnow()
        self.last_online[member_id] = now
        self.last_presence[member_id] = now
        info = {
            "id": msg.id,
            "author": member_id,
            "ts": msg.created_at,
            "len": len(msg.content),
            "words": len(msg.content.split()),
            "rich": bool(msg.attachments) or bool(msg.embeds) or ("http" in msg.content),
            "mentions": msg.content.count("@here") + msg.content.count("@everyone"),
            "mention_ids": [u.id for u in msg.mentions],
            "reply_to": msg.reference.resolved.author.id if msg.reference and msg.reference.resolved else None,
        }
        self.messages.append(info)
        if msg.created_at - self.last_message_ts >= timedelta(hours=24):
            log.debug(
                "Ghostbuster winner: %s",
                user_name(
                    (getattr(msg.guild, "get_member", lambda _id: None)(member_id))
                    or member_id
                ),
            )
            await self._rotate_single(msg.guild, ROLE_GHOSTBUSTER, member_id)
        self.last_message_ts = msg.created_at


    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if reaction.message.guild is None or reaction.message.guild.id != GUILD_ID:
            return
        if user.bot:
            return
        now = discord.utils.utcnow()
        self.last_online[user.id] = now
        self.last_presence[user.id] = now
        creator = None
        if isinstance(reaction.emoji, discord.Emoji):
            em = reaction.message.guild.get_emoji(reaction.emoji.id)
            if em and em.user:
                creator = em.user.id
        entry = {
            "ts": discord.utils.utcnow(),
            "msg": reaction.message.id,
            "msg_author": reaction.message.author.id,
            "emoji": str(reaction.emoji),
            "creator": creator,
            "user": user.id,
        }
        self.reactions.append(entry)

    # ── Badge Helpers ─────────────────────────────────────────────────────
    async def _rotate_single(self, guild: discord.Guild, role_id: int, user_id: int | None):
        """Rotate a single badge role to the specified user."""
        role = guild.get_role(role_id)
        if not role:
            log.debug(
                "Role ID %s not found in guild %s; skipping",
                role_id,
                guild_name(guild),
            )
            return

        changed = False
        for member in guild.members:
            if role in member.roles and member.id != user_id:
                await self._remove(member, role_id)
                changed = True

        if user_id:
            target = await self._get_member(guild, user_id)
            if target:
                if role not in target.roles:
                    await self._assign(target, role_id)
                    changed = True
            else:
                  log.warning(
                      "Member %s for role %s not found",
                      user_name(self.bot.get_user(user_id) or user_id),
                      role.name,
                  )
        else:
            log.debug("No qualifying member for %s", role.name)

        if not changed:
            log.debug("No changes for role %s", role.name)

    async def _assign_flag(self, guild: discord.Guild, member: discord.Member, role_id: int):
        """Assign the appropriate inactivity flag to a member."""
        for r in (ROLE_GHOST, ROLE_SHADOW_FLAG, ROLE_LURKER_FLAG, ROLE_NPC_FLAG):
            if r == 0:
                continue
            role = guild.get_role(r)
            if role and role in member.roles and r != role_id:
                await self._remove(member, r)
        role = guild.get_role(role_id)
        if role and role_id:
            if role not in member.roles:
                await self._assign(member, role_id)

    async def _sync_role(self, guild: discord.Guild, role_id: int, winners: list[int]):
        """Remove role from non-winners and add to winners."""
        role = guild.get_role(role_id)
        if not role:
            return
        current = {m.id for m in role.members}
        to_remove = current - set(winners)
        for uid in to_remove:
            member = guild.get_member(uid)
            if member:
                await self._remove(member, role_id)
        for uid in winners:
            member = await self._get_member(guild, uid)
            if member and role not in member.roles:
                await self._assign(member, role_id)

    # ── Badge Rotation Task ─────────────────────────────────────────────
    @tasks.loop(hours=24)
    async def badge_task(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return
        self.assign_counts.clear()
        now = discord.utils.utcnow()
        await self._refresh_presence_from_archive(now)
        cutoff14 = now - timedelta(days=14)
        cutoff30 = now - timedelta(days=30)
        bot_ids = {m.id for m in guild.members if m.bot}
        self.messages = [
            m for m in self.messages if m["ts"] >= cutoff30 and m["author"] not in bot_ids
        ]
        self.reactions = [
            r
            for r in self.reactions
            if r["ts"] >= cutoff30
            and r["user"] not in bot_ids
            and r["msg_author"] not in bot_ids
        ]

        counts = Counter(m["author"] for m in self.messages if m["ts"] >= cutoff14)
        top_poster = counts.most_common(1)[0][0] if counts else None
        log.debug(
            "Top Poster winner: %s",
            user_name(
                (getattr(guild, "get_member", lambda _id: None)(top_poster))
                or top_poster
            ),
        )
        await self._rotate_single(guild, ROLE_TOP_POSTER, top_poster)

        # tiered Top Poster and Reaction Magnet roles
        if hasattr(cfg, "TIERED_BADGES"):
            poster_ranks = [uid for uid, c in counts.most_common(30)
                            if c >= cfg.TIERED_BADGES['top_poster']['threshold']]
            react_counts = Counter(r["msg_author"] for r in self.reactions
                                   if r["ts"] >= cutoff14)
            react_ranks = [uid for uid, c in react_counts.most_common(30)
                           if c >= cfg.TIERED_BADGES['reaction_magnet']['threshold']]
            tier_roles = cfg.TIERED_BADGES
            poster_map = assign_tiers(poster_ranks, tier_roles['top_poster']['roles'])
            react_map = assign_tiers(react_ranks, tier_roles['reaction_magnet']['roles'])
            winners: dict[int, list[int]] = {}
            for uid, rid in poster_map.items():
                winners.setdefault(rid, []).append(uid)
            for uid, rid in react_map.items():
                winners.setdefault(rid, []).append(uid)
            for rid, users in winners.items():
                await self._sync_role(guild, rid, users)

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
        log.debug(
            "Certified Banger winner: %s",
            user_name(
                (getattr(guild, "get_member", lambda _id: None)(best)) or best
            ),
        )
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
        log.debug(
            "Top Curator winner: %s",
            user_name(
                (getattr(guild, "get_member", lambda _id: None)(top_curator))
                or top_curator
            ),
        )
        await self._rotate_single(guild, ROLE_TOP_CURATOR, top_curator)

        early_counts = Counter()
        for m in self.messages:
            if m["ts"] >= cutoff14:
                ts_la = m["ts"].astimezone(LA)
                minutes = ts_la.hour * 60 + ts_la.minute
                if 5 * 60 <= minutes <= 8 * 60 + 30:
                    early_counts[m["author"]] += 1
        early_bird = early_counts.most_common(1)[0][0] if early_counts else None
        log.debug(
            "Early Bird winner: %s",
            user_name(
                (getattr(guild, "get_member", lambda _id: None)(early_bird))
                or early_bird
            ),
        )
        await self._rotate_single(guild, ROLE_EARLY_BIRD, early_bird)

        summons = Counter(m["author"] for m in self.messages if m["ts"] >= cutoff30 for _ in range(m["mentions"]))
        summoner = summons.most_common(1)[0][0] if summons else None
        log.debug(
            "The Summoner winner: %s",
            user_name(
                (getattr(guild, "get_member", lambda _id: None)(summoner))
                or summoner
            ),
        )
        await self._rotate_single(guild, ROLE_SUMMONER, summoner)

        referenced = Counter(m["reply_to"] for m in self.messages if m["ts"] >= cutoff30 and m["reply_to"])
        lore_creator = referenced.most_common(1)[0][0] if referenced else None
        log.debug(
            "Lore Creator winner: %s",
            user_name(
                (getattr(guild, "get_member", lambda _id: None)(lore_creator))
                or lore_creator
            ),
        )
        await self._rotate_single(guild, ROLE_LORE_CREATOR, lore_creator)

        creator_counts = Counter(r["creator"] for r in self.reactions if r["ts"] >= cutoff30 and r["creator"])
        reaction_engineer = creator_counts.most_common(1)[0][0] if creator_counts else None
        log.debug(
            "Reaction Engineer winner: %s",
            user_name(
                (getattr(guild, "get_member", lambda _id: None)(reaction_engineer))
                or reaction_engineer
            ),
        )
        await self._rotate_single(guild, ROLE_REACTION_ENGINEER, reaction_engineer)

        cutoff5 = now - timedelta(days=5)

        recent_msgs = [m for m in self.messages if m["ts"] >= cutoff5]
        if recent_msgs:
            galaxy_brain = max(recent_msgs, key=lambda m: m.get("words", 0))["author"]
        else:
            galaxy_brain = None
        log.debug(
            "Galaxy Brain winner: %s",
            user_name(
                (getattr(guild, "get_member", lambda _id: None)(galaxy_brain))
                or galaxy_brain
            ),
        )
        await self._rotate_single(guild, ROLE_GALAXY_BRAIN, galaxy_brain)

        word_counts = defaultdict(list)
        for m in recent_msgs:
            word_counts[m["author"]].append(m.get("words", 0))
        wordsmith = None
        best_avg = 0.0
        for uid, words in word_counts.items():
            if len(words) >= 3:
                avg = sum(words) / len(words)
                if avg > best_avg:
                    best_avg = avg
                    wordsmith = uid
        log.debug(
            "Wordsmith winner: %s",
            user_name(
                (getattr(guild, "get_member", lambda _id: None)(wordsmith))
                or wordsmith
            ),
        )
        await self._rotate_single(guild, ROLE_WORDSMITH, wordsmith)

        reaction_map5 = Counter()
        for r in self.reactions:
            if r["ts"] >= cutoff5:
                reaction_map5[r["msg"]] += 1
        sniper_scores = defaultdict(list)
        for m in self.messages:
            if m["ts"] >= cutoff5:
                ratio = reaction_map5[m["id"]] / max(m.get("words", 1), 1)
                sniper_scores[m["author"]].append(ratio)
        sniper = None
        best_ratio = 0.0
        for uid, ratios in sniper_scores.items():
            avg = sum(ratios) / len(ratios)
            if avg > best_ratio:
                best_ratio = avg
                sniper = uid
        log.debug(
            "Sniper winner: %s",
            user_name(
                (getattr(guild, "get_member", lambda _id: None)(sniper)) or sniper
            ),
        )
        await self._rotate_single(guild, ROLE_SNIPER, sniper)

        night_counts = Counter()
        for m in self.messages:
            if m["ts"] >= cutoff14:
                hour = m["ts"].astimezone(LA).hour
                if hour >= 22 or hour < 4:
                    night_counts[m["author"]] += 1
        night_owl = night_counts.most_common(1)[0][0] if night_counts else None
        log.debug(
            "Night Owl winner: %s",
            user_name(
                (getattr(guild, "get_member", lambda _id: None)(night_owl))
                or night_owl
            ),
        )
        await self._rotate_single(guild, ROLE_NIGHT_OWL, night_owl)

        mention_counts = Counter(
            uid
            for m in self.messages
            if m["ts"] >= cutoff14
            for uid in m.get("mention_ids", [])
        )
        comeback_kid = mention_counts.most_common(1)[0][0] if mention_counts else None
        log.debug(
            "Comeback Kid winner: %s",
            user_name(
                (getattr(guild, "get_member", lambda _id: None)(comeback_kid))
                or comeback_kid
            ),
        )
        await self._rotate_single(guild, ROLE_COMEBACK_KID, comeback_kid)

        seven_days = timedelta(days=7)
        cutoff7 = now - seven_days
        msg_count7 = Counter(m["author"] for m in self.messages if m["ts"] >= cutoff7)

        for member in guild.members:
            if member.bot:
                continue

            presence_ts = self.last_presence.get(member.id)
            if presence_ts is None:
                presence_ts = self.last_online.get(member.id)
            has_recent_presence = (
                presence_ts is not None and (now - presence_ts) <= seven_days
            )
            if not has_recent_presence:
                await self._assign_flag(guild, member, ROLE_GHOST)
                continue

            msgs7 = msg_count7[member.id]
            if msgs7 == 0:
                await self._assign_flag(guild, member, ROLE_LURKER_FLAG)
                continue
            if 1 <= msgs7 <= 5:
                await self._assign_flag(guild, member, ROLE_NPC_FLAG)
                continue

            await self._assign_flag(guild, member, 0)
    # ── Internal Role Helpers ──────────────────────────────────────────────────
    async def _assign(self, member: discord.Member, role_id: int):
        if member.bot:
            log.debug("Skipping role %s for bot %s", role_id, user_name(member))
            return
        role = member.guild.get_role(role_id)
        if not role:
            log.error(
                "ERROR - role_id=%s not found in guild %s",
                role_id,
                guild_name(member.guild),
            )
            return
        if role_id != ROLE_NPC_FLAG:
            npc = member.guild.get_role(ROLE_NPC_FLAG)
            if npc and npc in member.roles:
                await self._remove(member, ROLE_NPC_FLAG)
        if role in member.roles:
            log.debug("Member %s already has role %s", user_name(member), role_id)
            return
        try:
            self.assign_counts[role_id] += 1
            await member.add_roles(role, reason="RoleCog auto-assign")
        except discord.Forbidden:
            log.error(
                "Missing permissions to assign role %s to %s. "
                "Ensure the bot's role is above the target role and has Manage Roles.",
                role_id,
                user_name(member),
            )
        except Exception as e:
            log.error(
                "Failed assigning role %s to %s: %s", role_id, user_name(member), e
            )

    async def _remove(self, member: discord.Member, role_id: int):
        role = member.guild.get_role(role_id)
        if not role:
            log.error(
                "ERROR - role_id=%s not found in guild %s",
                role_id,
                guild_name(member.guild),
            )
            return
        if role not in member.roles:
            log.debug(
                "Member %s missing role %s on remove; fetching",
                user_name(member),
                role_id,
            )
            try:
                refreshed = await member.guild.fetch_member(member.id)
            except discord.NotFound:
                log.warning(
                    "Member %s disappeared while removing role %s",
                    user_name(member),
                    role_id,
                )
                return
            except discord.HTTPException as exc:
                log.error("Failed to refresh member %s: %s", user_name(member), exc)
                return
            if role not in refreshed.roles:
                log.debug(
                    "Member %s no longer has role %s",
                    user_name(member),
                    role_id,
                )
                return
            member = refreshed
        try:
            await member.remove_roles(role, reason="RoleCog auto-remove")
        except discord.Forbidden:
            log.error(
                "Missing permissions to remove role %s from %s. "
                "Ensure the bot's role is above the target role and has Manage Roles.",
                role_id,
                user_name(member),
            )
        except Exception as e:
            log.error(
                "Failed removing role %s from %s: %s", role_id, user_name(member), e
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleCog(bot))
