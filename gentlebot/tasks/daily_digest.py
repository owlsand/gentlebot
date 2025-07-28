from __future__ import annotations
import logging
from datetime import datetime, timedelta
import asyncio
import re
import asyncpg
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import discord
from discord.ext import commands

from .. import bot_config as cfg
from ..util import build_db_url

log = logging.getLogger(f"gentlebot.{__name__}")

LA = pytz.timezone("America/Los_Angeles")

# ─── Helper Functions ──────────────────────────────────────────────────────

def assign_tiers(rankings: list[int], roles: dict[str, int]) -> dict[int, int]:
    """Return user→role mapping for tiered badges using fixed ranges."""

    result: dict[int, int] = {}
    tiers = (
        ("gold", 0, 3),   # top 3
        ("silver", 3, 8), # ranks 4–8
        ("bronze", 8, 15), # ranks 9–15
    )
    for name, start, end in tiers:
        role_id = roles.get(name, 0)
        for idx in range(start, min(end, len(rankings))):
            result[rankings[idx]] = role_id
    return result


class DailyDigestCog(commands.Cog):
    """Daily Digest scheduler for engagement badges."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler: AsyncIOScheduler | None = None
        self.pool: asyncpg.Pool | None = None

    async def cog_load(self) -> None:
        url = build_db_url()
        if url:
            url = url.replace("postgresql+asyncpg://", "postgresql://")

            async def _init(conn: asyncpg.Connection) -> None:
                await conn.execute("SET search_path=discord,public")

            self.pool = await asyncpg.create_pool(url, init=_init)
        self.scheduler = AsyncIOScheduler(timezone=LA)
        trigger = CronTrigger(hour=8, minute=30, timezone=LA)
        self.scheduler.add_job(self.run_digest, trigger)
        self.scheduler.start()
        log.info("DailyDigest scheduler started")

    async def cog_unload(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        if self.pool:
            await self.pool.close()
            self.pool = None

    # ── Core Logic ────────────────────────────────────────────────────────
    async def _top_posters(self, days: int = 14) -> list[tuple[int, int, datetime]]:
        if not self.pool:
            return []
        rows = await self.pool.fetch(
            """
            SELECT author_id,
                   COUNT(*) AS c,
                   MAX(created_at) AS last_ts
            FROM discord.message
            WHERE created_at >= now() - $1::interval
            GROUP BY author_id
            HAVING COUNT(*) >= $2
            ORDER BY c DESC, last_ts ASC
            LIMIT 30
            """,
            timedelta(days=days),
            cfg.TIERED_BADGES['top_poster']['threshold'],
        )
        return [(r["author_id"], r["c"], r["last_ts"]) for r in rows]

    async def _reaction_magnets(self, days: int = 14) -> list[tuple[int, int, datetime]]:
        if not self.pool:
            return []
        rows = await self.pool.fetch(
            """
            SELECT m.author_id,
                   COUNT(*) AS c,
                   MAX(r.event_at) AS last_ts
            FROM discord.reaction_event r
            JOIN discord.message m ON m.message_id = r.message_id
            WHERE r.action = 1 AND r.event_at >= now() - $1::interval
            GROUP BY m.author_id
            HAVING COUNT(*) >= $2
            ORDER BY c DESC, last_ts ASC
            LIMIT 30
            """,
            timedelta(days=days),
            cfg.TIERED_BADGES['reaction_magnet']['threshold'],
        )
        return [(r["author_id"], r["c"], r["last_ts"]) for r in rows]

    async def _yesterday_top_poster(self) -> list[tuple[int, int]]:
        if not self.pool:
            return []
        now = datetime.now(tz=LA)
        start = datetime(now.year, now.month, now.day, tzinfo=LA) - timedelta(days=1)
        end = start + timedelta(days=1)
        rows = await self.pool.fetch(
            """
            SELECT author_id,
                   COUNT(*) AS c,
                   MAX(created_at) AS last_ts
            FROM discord.message
            WHERE created_at >= $1 AND created_at < $2
            GROUP BY author_id
            ORDER BY c DESC, last_ts ASC
            LIMIT 5
            """,
            start,
            end,
        )
        return [(r["author_id"], r["c"]) for r in rows]

    async def _assign_roles(self, guild: discord.Guild, mapping: dict[int, int]) -> None:
        for user_id, role_id in mapping.items():
            if role_id == 0:
                continue
            member = guild.get_member(user_id)
            role = guild.get_role(role_id)
            if member and role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Daily Digest")
                except discord.HTTPException:
                    log.warning("Failed to assign %s to %s", role.name, member)

    async def _sync_role(self, guild: discord.Guild, role_id: int, winners: list[int]) -> None:
        """Remove role from non-winners and add to winners."""
        role = guild.get_role(role_id)
        if not role:
            return
        current = {m.id for m in role.members}
        to_remove = current - set(winners)
        for uid in to_remove:
            member = guild.get_member(uid)
            if member:
                try:
                    await member.remove_roles(role, reason="Daily Digest rotation")
                except discord.HTTPException:
                    log.warning("Failed to remove %s from %s", role.name, member)
        for uid in winners:
            member = guild.get_member(uid)
            if member and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Daily Digest rotation")
                except discord.HTTPException:
                    log.warning("Failed to assign %s to %s", role.name, member)

    async def _win_count(self, role_id: int, user_id: int) -> int:
        if not self.pool:
            return 0
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) AS c FROM discord.role_event WHERE role_id=$1 AND user_id=$2 AND action=1",
            role_id,
            user_id,
        )
        return int(row["c"]) if row else 0

    async def _unpin_message(self, channel_id: int, message_id: int) -> None:
        channel = self.bot.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            try:
                msg = await channel.fetch_message(message_id)
                await msg.unpin()
            except discord.HTTPException:
                log.warning("Failed to unpin digest message %s", message_id)

    async def _last_hero_time(self, user_id: int) -> datetime | None:
        if not self.pool:
            return None
        row = await self.pool.fetchrow(
            """
            SELECT event_at
            FROM discord.role_event
            WHERE role_id=$1 AND user_id=$2 AND action=1
            ORDER BY event_at DESC
            LIMIT 1
            """,
            cfg.ROLE_DAILY_HERO,
            user_id,
        )
        return row["event_at"] if row else None

    async def run_digest(self) -> None:
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            return
        log.info("Running Daily Digest")

        top_msgs = await self._top_posters(14)
        top_reacts = await self._reaction_magnets(14)
        hero_candidates = await self._yesterday_top_poster()
        hero: int | None = None
        for uid, _ in hero_candidates:
            last = await self._last_hero_time(uid)
            if not last or last <= datetime.now(tz=LA) - timedelta(hours=72):
                hero = uid
                break

        tier_roles = cfg.TIERED_BADGES
        msg_map = assign_tiers([uid for uid, _, _ in top_msgs], tier_roles['top_poster']['roles'])
        react_map = assign_tiers([uid for uid, _, _ in top_reacts], tier_roles['reaction_magnet']['roles'])

        winners: dict[int, list[int]] = {}
        for user_id, role_id in (msg_map | react_map).items():
            winners.setdefault(role_id, []).append(user_id)
        for role_id, users in winners.items():
            await self._sync_role(guild, role_id, users)

        if hero:
            await self._sync_role(guild, cfg.ROLE_DAILY_HERO, [hero])
            member = guild.get_member(hero)
            if member:
                try:
                    # await member.send(
                    #     "Congrats! You're today's Daily Hero. Run /suggest-topic to keep chats lively!"
                    # )
                    pass  # message sending disabled for auditing
                except discord.HTTPException:
                    log.warning("Failed to DM Daily Hero %s", member)


        channel_id = getattr(cfg, 'LOBBY_CHANNEL_ID', getattr(cfg, 'DAILY_PING_CHANNEL', 0))
        channel = self.bot.get_channel(channel_id)
        if not channel:
            log.error("Digest channel not found: %s", channel_id)
            return
        if hero:
            member = guild.get_member(hero)
        else:
            member = None
        if isinstance(channel, discord.TextChannel):
            topic = channel.topic or ""
            topic = re.sub(r"^👑 Daily Hero:.*?\| ?", "", topic)
            if member:
                topic = f"\U0001f451 Daily Hero: {member.display_name} (expires 08:30 PT) | {topic}"
            try:
                await channel.edit(topic=topic[:1024])
            except discord.HTTPException:
                log.warning("Failed to update channel topic")
        now = datetime.now(tz=LA)
        def _m(uid: int) -> str:
            member = guild.get_member(uid)
            return member.mention if member else f"<@{uid}>"

        async def _wins(role_id: int, uid: int) -> int:
            return await self._win_count(role_id, uid)

        poster_roles = tier_roles['top_poster']['roles']
        react_roles = tier_roles['reaction_magnet']['roles']

        tasks: list[asyncio.Task[int]] = []
        if top_msgs:
            tasks.append(asyncio.create_task(_wins(poster_roles['gold'], top_msgs[0][0])))
        if len(top_msgs) > 1:
            tasks.append(asyncio.create_task(_wins(poster_roles['silver'], top_msgs[1][0])))
        if len(top_msgs) > 2:
            tasks.append(asyncio.create_task(_wins(poster_roles['bronze'], top_msgs[2][0])))
        if len(top_msgs) > 3:
            tasks.append(asyncio.create_task(_wins(poster_roles['bronze'], top_msgs[3][0])))
        if top_reacts:
            tasks.append(asyncio.create_task(_wins(react_roles['gold'], top_reacts[0][0])))
        if len(top_reacts) > 1:
            tasks.append(asyncio.create_task(_wins(react_roles['silver'], top_reacts[1][0])))
        if len(top_reacts) > 2:
            tasks.append(asyncio.create_task(_wins(react_roles['bronze'], top_reacts[2][0])))
        if len(top_reacts) > 3:
            tasks.append(asyncio.create_task(_wins(react_roles['bronze'], top_reacts[3][0])))
        counts = []
        if tasks:
            counts = await asyncio.gather(*tasks)

        c_iter = iter(counts)
        def next_count() -> int:
            return next(c_iter, 0)

        desc = [f"**Gentlefolk Daily Digest {now.strftime('%b %d')}**"]
        if hero:
            desc.append(f"**Daily Hero:** \U0001f451 {_m(hero)}")
        else:
            desc.append("**Daily Hero:** No Daily Hero (0 msgs)")
        desc.append("\n**Top Poster**")
        if top_msgs:
            gold_c = next_count()
            desc.append(f"\U0001f947 {_m(top_msgs[0][0])} _(x{gold_c})_")
        if len(top_msgs) > 1:
            silver_c = next_count()
            desc.append(f"\U0001f948 {_m(top_msgs[1][0])} _(x{silver_c})_")
        bronzes = []
        if len(top_msgs) > 2:
            bronzes.append(_m(top_msgs[2][0]))
            next_count()
        if len(top_msgs) > 3:
            bronzes.append(_m(top_msgs[3][0]))
            next_count()
        if bronzes:
            desc.append("\U0001f949 " + " / ".join(bronzes))
        desc.append("\n**Reaction Magnet**")
        if top_reacts:
            gold_c = next_count()
            desc.append(f"\U0001f947 {_m(top_reacts[0][0])} _(x{gold_c})_")
        if len(top_reacts) > 1:
            silver_c = next_count()
            desc.append(f"\U0001f948 {_m(top_reacts[1][0])} _(x{silver_c})_")
        bronzes = []
        if len(top_reacts) > 2:
            bronzes.append(_m(top_reacts[2][0]))
            next_count()
        if len(top_reacts) > 3:
            bronzes.append(_m(top_reacts[3][0]))
            next_count()
        if bronzes:
            desc.append("\U0001f949 " + " / ".join(bronzes))

        embed = discord.Embed(description="\n".join(desc))
        # msg = await channel.send("Daily Digest", embed=embed)
        # try:
        #     await msg.pin()
        #     self.scheduler.add_job(
        #         self._unpin_message,
        #         "date",
        #         run_date=now + timedelta(hours=24),
        #         args=[channel.id, msg.id],
        #     )
        # except discord.HTTPException:
        #     log.warning("Failed to pin digest message")
        if self.pool:
            await self.pool.execute(
                "INSERT INTO discord.experiment_results (experiment_id, day, metric, value) VALUES ('H1_ROLE_DIGEST', current_date, 'digest_sent', 1)"
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailyDigestCog(bot))
