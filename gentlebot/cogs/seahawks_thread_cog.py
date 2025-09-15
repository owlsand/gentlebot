"""Create Seahawks game day threads with projections and odds."""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Any, Dict, List, Tuple

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
        # Track created threads and score update progress
        self.threads: Dict[str, discord.Thread] = {}
        self.opponents: Dict[str, str] = {}
        self.quarters_sent: Dict[str, int] = {}
        self.game_task.start()
        self.score_task.start()

    async def cog_unload(self) -> None:  # pragma: no cover - cleanup
        self.game_task.cancel()
        self.score_task.cancel()

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
        # Win probability comes from the predictor endpoint
        pred_url = (
            "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
            f"events/{game_id}/competitions/{game_id}/predictor"
        )
        resp = requests.get(pred_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        def _parse_team(team: dict[str, Any]) -> tuple[str, float]:
            """Return (team_id, win_probability)."""
            ref = team.get("team", {}).get("$ref", "")
            team_id = ref.rstrip("/").split("/")[-1].split("?")[0]
            stats = {s.get("name"): s for s in team.get("statistics", [])}
            win_stat = (
                stats.get("gameProjectionProbability")
                or stats.get("teamOddsWinPercentage")
                or stats.get("gameProjection")
            )
            win = win_stat.get("value", 0.0) / 100 if win_stat else 0.0
            return team_id, win

        home_id, home_win = _parse_team(data.get("homeTeam", {}))
        away_id, away_win = _parse_team(data.get("awayTeam", {}))

        # Spread and over/under for projected scores come from the summary API
        sum_url = (
            "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?"
            f"event={game_id}"
        )
        resp2 = requests.get(sum_url, timeout=10)
        resp2.raise_for_status()
        pick = resp2.json().get("pickcenter", [])
        over_under = pick[0].get("overUnder") if pick else None
        spread = pick[0].get("spread") if pick else None
        if over_under is not None and spread is not None:
            home_score = over_under / 2 - spread / 2
            away_score = over_under - home_score
            if home_id == "26":
                sea_score, opp_score = home_score, away_score
            else:
                sea_score, opp_score = away_score, home_score
        else:
            sea_score = opp_score = 0.0

        if home_id == "26":
            sea_win, opp_win = home_win, away_win
        else:
            sea_win, opp_win = away_win, home_win

        return {
            "sea_score": sea_score,
            "opp_score": opp_score,
            "sea_win": sea_win,
            "opp_win": opp_win,
        }

    def fetch_linescores(self, game_id: str) -> List[Tuple[int, int]]:
        """Return per-quarter scoring tuples for Seahawks and opponent.

        Filters out the trailing total row included in ESPN's data so
        each tuple represents an actual period (quarter or overtime).
        """
        url = (
            "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?"
            f"event={game_id}"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        box = resp.json().get("boxscore", {})
        teams = box.get("teams", [])
        if len(teams) != 2:
            return []
        sea_team = next(
            (t for t in teams if t.get("team", {}).get("abbreviation") == "SEA"),
            None,
        )
        opp_team = next(
            (t for t in teams if t.get("team", {}).get("abbreviation") != "SEA"),
            None,
        )
        if not sea_team or not opp_team:
            return []
        sea_lines = [int(ls.get("value", 0)) for ls in sea_team.get("linescores", [])]
        opp_lines = [int(ls.get("value", 0)) for ls in opp_team.get("linescores", [])]

        def _strip_total(lines: List[int]) -> List[int]:
            """Remove trailing total row if present."""
            if len(lines) >= 2 and lines[-1] == sum(lines[:-1]):
                return lines[:-1]
            return lines

        sea_lines = _strip_total(sea_lines)
        opp_lines = _strip_total(opp_lines)
        quarters: List[Tuple[int, int]] = []
        for idx in range(min(len(sea_lines), len(opp_lines))):
            quarters.append((sea_lines[idx], opp_lines[idx]))
        return quarters

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
                thread = await channel.create_thread(
                    name=title,
                    auto_archive_duration=1440,
                    type=discord.ChannelType.public_thread,
                )
            except Exception:  # pragma: no cover - network
                log.exception("Failed to create thread %s", title)
                continue
            try:
                proj = self.fetch_projection(g["id"])
                await thread.send(self._thread_message(proj, g["opponent"]))
            except Exception:  # pragma: no cover - network
                log.exception("Failed to send message for %s", title)
            self.opened.add(g["id"])
            self.threads[g["id"]] = thread
            self.opponents[g["id"]] = g["opponent"]
            self.quarters_sent[g["id"]] = 0

    # ---- background loop -------------------------------------------------------
    @tasks.loop(minutes=30)
    async def game_task(self) -> None:
        await self.bot.wait_until_ready()
        await self._open_threads()

    async def _update_scores(self) -> None:
        """Send quarter score updates to active game threads."""
        for gid, thread in list(self.threads.items()):
            try:
                lines = self.fetch_linescores(gid)
            except Exception:  # pragma: no cover - network
                log.exception("Failed to fetch scores for %s", gid)
                continue
            posted = self.quarters_sent.get(gid, 0)
            if len(lines) <= posted:
                continue
            sea_tot = opp_tot = 0
            for qnum, (sea_q, opp_q) in enumerate(lines, start=1):
                sea_tot += sea_q
                opp_tot += opp_q
                if qnum <= posted:
                    continue
                msg = (
                    f"End of Q{qnum}: Seahawks {sea_tot} - {self.opponents.get(gid, 'Opponent')} {opp_tot}"
                )
                try:
                    await thread.send(msg)
                except Exception:  # pragma: no cover - network
                    log.exception("Failed to send score update for %s Q%s", gid, qnum)
            self.quarters_sent[gid] = len(lines)

    @tasks.loop(minutes=5)
    async def score_task(self) -> None:
        await self.bot.wait_until_ready()
        await self._update_scores()


async def setup(bot: commands.Bot):
    await bot.add_cog(SeahawksThreadCog(bot))
