"""Create Seahawks game day threads with projections and odds."""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Any

import requests
from dateutil import parser
import pytz

import discord
from discord.ext import commands, tasks

from .. import bot_config as cfg

log = logging.getLogger(f"gentlebot.{__name__}")

PST = pytz.timezone("America/Los_Angeles")


class SeahawksThreadCog(commands.Cog):
    """Background task that opens Seahawks game threads."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.opened: set[str] = set()
        self.game_task.start()

    async def cog_unload(self) -> None:  # pragma: no cover - cleanup
        self.game_task.cancel()

    # ---- external data helpers -------------------------------------------------
    def fetch_schedule(self) -> list[dict[str, Any]]:
        """Return upcoming Seahawks games with opponent and start time (UTC)."""
        url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/sea/schedule"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        games: list[dict[str, Any]] = []
        for event in resp.json().get("events", []):
            comp = event.get("competitions", [{}])[0]
            start = parser.isoparse(comp.get("date")).astimezone(timezone.utc)
            gid = event.get("id")
            try:
                opp = next(
                    c for c in comp.get("competitors", [])
                    if c.get("team", {}).get("abbreviation") != "SEA"
                )
            except StopIteration:
                # Bye week entries only list Seattle as a competitor
                continue
            games.append(
                {
                    "id": gid,
                    "opponent": opp.get("team", {}).get("displayName", "Opponent"),
                    "short": event.get("shortName", "SEA game"),
                    "start": start,
                }
            )
        return games

    def fetch_projection(self, game_id: str) -> dict[str, float]:
        """Return projected score and win probability for each team."""
        url = f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{game_id}/competitions/{game_id}/predictor"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        home = data.get("homeTeam", {})
        away = data.get("awayTeam", {})
        # ESPN predictor uses 'gameProjection' and 'gameProjectionProb' fields
        return {
            "sea_score": home.get("gameProjection", 0.0) if home.get("teamId") == "26" else away.get("gameProjection", 0.0),
            "opp_score": away.get("gameProjection", 0.0) if home.get("teamId") == "26" else home.get("gameProjection", 0.0),
            "sea_win": home.get("gameProjectionProbability", 0.0) if home.get("teamId") == "26" else away.get("gameProjectionProbability", 0.0),
            "opp_win": away.get("gameProjectionProbability", 0.0) if home.get("teamId") == "26" else home.get("gameProjectionProbability", 0.0),
        }

    # ---- helpers ----------------------------------------------------------------
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _thread_title(self, short: str, start_pst: datetime) -> str:
        time_str = start_pst.strftime("%-m/%-d, %-I:%M%p").lower()
        return f"🏈 {short} ({time_str} PST)"

    def _thread_message(self, proj: dict[str, float], opponent: str) -> str:
        return (
            f"Projected score: Seahawks {proj['sea_score']:.0f} - {opponent} {proj['opp_score']:.0f}\n"
            f"Win odds: Seahawks {proj['sea_win']*100:.1f}%, {opponent} {proj['opp_win']*100:.1f}%"
        )

    async def _open_threads(self) -> None:
        now = self._now()
        try:
            games = self.fetch_schedule()
        except Exception:  # pragma: no cover - network
            log.exception("Failed to fetch Seahawks schedule")
            return
        for g in games:
            if g["id"] in self.opened:
                continue
            start_pst = g["start"].astimezone(PST)
            open_time = PST.localize(datetime.combine(start_pst.date(), time(9, 0))).astimezone(timezone.utc)
            if not (open_time <= now < g["start"]):
                continue
            channel = self.bot.get_channel(cfg.SPORTS_CHANNEL_ID)
            if not isinstance(channel, discord.TextChannel):
                log.error("Sports channel not found")
                self.opened.add(g["id"])
                continue
            title = self._thread_title(g["short"], start_pst)
            try:
                thread = await channel.create_thread(name=title, auto_archive_duration=1440)
            except Exception:  # pragma: no cover - network
                log.exception("Failed to create thread %s", title)
                continue
            try:
                proj = self.fetch_projection(g["id"])
                await thread.send(self._thread_message(proj, g["opponent"]))
            except Exception:  # pragma: no cover - network
                log.exception("Failed to send message for %s", title)
            self.opened.add(g["id"])

    # ---- background loop -------------------------------------------------------
    @tasks.loop(minutes=30)
    async def game_task(self) -> None:
        await self.bot.wait_until_ready()
        await self._open_threads()


async def setup(bot: commands.Bot):
    await bot.add_cog(SeahawksThreadCog(bot))
