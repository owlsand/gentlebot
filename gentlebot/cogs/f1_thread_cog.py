"""Create threads for F1 sessions stored in Postgres."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from dateutil import parser

import asyncpg
import discord
from discord.ext import commands, tasks

from ..db import get_pool
from .. import bot_config as cfg

log = logging.getLogger(f"gentlebot.{__name__}")

# Los Angeles timezone for thread titles/messages
LA_TZ = ZoneInfo("America/Los_Angeles")
# Time window to open threads ahead of session start
THREAD_OPEN_WINDOW = timedelta(hours=2)


def iso_to_flag(iso: str) -> str:
    """Return the emoji flag for a 2-letter ISO country code."""
    return chr(0x1F1E6 + ord(iso[0].upper()) - 65) + chr(0x1F1E6 + ord(iso[1].upper()) - 65)


class F1ThreadCog(commands.Cog):
    """Background task that opens and deletes F1 session threads."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: asyncpg.Pool | None = None
        self.session_task.start()

    async def cog_load(self) -> None:
        try:
            self.pool = await get_pool()
        except RuntimeError:
            log.warning("PG_DSN required for F1ThreadCog")
            return
        await self._refresh_schedule()

    async def cog_unload(self) -> None:
        self.session_task.cancel()
        self.pool = None

    async def _refresh_schedule(self) -> None:
        """Fetch sessions and insert any new ones."""
        try:
            sessions = self.fetch_schedule()
        except Exception:  # pragma: no cover - network
            log.exception("Failed to fetch F1 schedule")
            return
        if not self.pool:
            return
        for s in sessions:
            await self.pool.execute(
                """
                INSERT INTO discord.f1_session (country_iso, year, gp_name, session, starts_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (year, gp_name, session) DO NOTHING
                """,
                s["country_iso"],
                s["year"],
                s["gp_name"],
                s["session"],
                s["starts_at"],
            )

    def fetch_schedule(self) -> list[dict]:
        """Return list of qualifying and race sessions with metadata."""
        year = datetime.now(timezone.utc).year
        url = f"https://f1calendar.com/api/calendar?season={year}"
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # pragma: no cover - network
            log.exception("Failed to fetch F1 schedule: %s", exc)
            return []

        iso_map = {
            "Australian": "AU",
            "Chinese": "CN",
            "Japanese": "JP",
            "Bahrain": "BH",
            "Saudi Arabian": "SA",
            "Miami": "US",
            "Emilia Romagna": "IT",
            "Monaco": "MC",
            "Spanish": "ES",
            "Canadian": "CA",
            "Austrian": "AT",
            "British": "GB",
            "Belgian": "BE",
            "Hungarian": "HU",
            "Dutch": "NL",
            "Italian": "IT",
            "Azerbaijan": "AZ",
            "Singapore": "SG",
            "United States": "US",
            "Mexico City": "MX",
            "Brazilian": "BR",
            "Las Vegas": "US",
            "Qatar": "QA",
            "Abu Dhabi": "AE",
        }

        sessions: list[dict] = []
        for race in data.get("races", []):
            gp_name_full = race.get("name", "")
            if not gp_name_full:
                continue
            gp_name = gp_name_full.replace(" Grand Prix", "")
            country_iso = iso_map.get(gp_name, "")
            for name, iso in race.get("sessions", {}).items():
                if name not in {"Qualifying", "Grand Prix"}:
                    continue
                session_code = "QUALI" if name == "Qualifying" else "RACE"
                dt = parser.isoparse(iso).astimezone(timezone.utc)
                sessions.append(
                    {
                        "country_iso": country_iso,
                        "year": dt.year,
                        "gp_name": gp_name,
                        "session": session_code,
                        "starts_at": dt,
                    }
                )
        return sessions

    async def _due_sessions(self) -> list[asyncpg.Record]:
        if not self.pool:
            return []
        return await self.pool.fetch(
            """
            SELECT id, country_iso, year, gp_name, session, starts_at
            FROM discord.f1_session
            WHERE session IN ('QUALI','RACE')
              AND starts_at >= now()
              AND starts_at <= now() + $1
              AND thread_id IS NULL
            ORDER BY starts_at
            LIMIT 5
            """,
            THREAD_OPEN_WINDOW,
        )

    def _make_title(self, row: asyncpg.Record) -> str:
        flag = iso_to_flag(row["country_iso"])
        session_word = "Qualifying" if row["session"] == "QUALI" else "Grand Prix"
        local = row["starts_at"].astimezone(LA_TZ).strftime("%a %H:%M %Z")
        title = f"{flag} {row['year']} {row['gp_name']} GP | {session_word} — {local}"
        return title[:90]

    def _make_message(self, row: asyncpg.Record) -> str:
        flag = iso_to_flag(row["country_iso"])
        session_word = "Qualifying" if row["session"] == "QUALI" else "Grand Prix"
        local = row["starts_at"].astimezone(LA_TZ).strftime("%a %H:%M %Z")
        flagline = (
            "Green light (Q1) at the time above." if row["session"] == "QUALI" else "Lights out at the time above."
        )
        return (
            f"**{flag} {row['year']} {row['gp_name']} GP – {session_word}**\n\n"
            f"⏱ **Session start:** {local}\n"
            f"🏁 {flagline}\n\n"
            "**Quick links**\n"
            "• Live timing — https://f1live.com\n"
            "• `/f1standings` — driver & constructor tables\n"
            "• Session schedule — https://f1tv.formula1.com/schedule\n\n"
            "> Watching on delay? Mute this thread to stay spoiler‑free."
        )

    async def _mark_started(self, session_id: int, thread_id: int) -> None:
        if not self.pool:
            return
        await self.pool.execute(
            "UPDATE discord.f1_session SET thread_id=$1 WHERE id=$2",
            thread_id,
            session_id,
        )

    async def _delete_after(self, thread: discord.Thread, session_id: int, delay: float = 86400) -> None:
        await asyncio.sleep(delay)
        try:
            await thread.delete()
        except Exception as exc:  # pragma: no cover - delete failure is ok
            log.warning("Failed to delete thread %s: %s", thread.id, exc)
        if self.pool:
            await self.pool.execute(
                "UPDATE discord.f1_session SET thread_id=NULL WHERE id=$1",
                session_id,
            )

    @tasks.loop(minutes=5)
    async def session_task(self) -> None:
        await self.bot.wait_until_ready()
        await self._refresh_schedule()
        await self._open_threads()

    async def _open_threads(self) -> None:
        sessions = await self._due_sessions()
        if not sessions:
            return
        channel = self.bot.get_channel(cfg.F1_DISCORD_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            log.error("F1 channel not found")
            return
        for row in sessions:
            title = self._make_title(row)
            try:
                thread = await channel.create_thread(name=title, auto_archive_duration=1440)
            except Exception:
                log.exception("Failed to create thread %s", title)
                continue
            try:
                await thread.send(self._make_message(row))
            except Exception:
                log.exception("Failed to send opening message for %s", title)
            await self._mark_started(row["id"], thread.id)
            self.bot.loop.create_task(self._delete_after(thread, row["id"]))


async def setup(bot: commands.Bot):
    await bot.add_cog(F1ThreadCog(bot))
