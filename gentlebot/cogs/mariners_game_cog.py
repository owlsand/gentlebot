"""Automatically post Mariners game summaries after each final result."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import asyncio
import requests
from requests.adapters import HTTPAdapter, Retry
import pytz
import asyncpg

import discord
from discord.ext import commands, tasks

from .sports_cog import TEAM_ID, STATS_TIMEOUT, PST_TZ
from .. import bot_config as cfg
from ..db import get_pool

log = logging.getLogger(f"gentlebot.{__name__}")


class MarinersGameCog(commands.Cog):
    """Background task posting a summary after each Mariners game."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.posted: set[int] = set()

    async def cog_load(self) -> None:  # pragma: no cover - startup
        self.game_task.start()

    async def cog_unload(self) -> None:  # pragma: no cover - cleanup
        self.game_task.cancel()

    # ------------------------------------------------------------------ helpers
    def _schedule_dates(self) -> list[str]:
        today = datetime.now(PST_TZ).date()
        yesterday = today - timedelta(days=1)
        return [today.isoformat(), yesterday.isoformat()]

    async def _ensure_table(self) -> None:
        if not self.pool:
            return
        await self.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS mariners_posted (
                game_pk BIGINT PRIMARY KEY,
                posted_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

    async def _load_posted(self) -> None:
        if not self.pool:
            return
        rows = await self.pool.fetch("SELECT game_pk FROM mariners_posted")
        self.posted.update(int(r[0]) for r in rows)

    async def _save_posted(self, game_pk: int) -> None:
        if not self.pool:
            return
        try:
            await self.pool.execute(
                "INSERT INTO mariners_posted (game_pk) VALUES ($1) ON CONFLICT DO NOTHING",
                game_pk,
            )
        except Exception as exc:  # pragma: no cover - database
            log.warning("Failed to record posted game %s: %s", game_pk, exc)

    def fetch_game_summary(self) -> Optional[Dict[str, Any]]:
        """Return a summary dict for the most recent final game.

        The dict contains fields consumed by :meth:`build_message`. Network
        errors return ``None``.
        """
        try:
            with requests.Session() as session:
                retries = Retry(
                    total=3,
                    backoff_factor=1,
                    status_forcelist=[500, 502, 503, 504],
                    allowed_methods=["GET"],
                )
                adapter = HTTPAdapter(max_retries=retries)
                session.mount("https://", adapter)
                session.mount("http://", adapter)

                for date in self._schedule_dates():
                    url = (
                        "https://statsapi.mlb.com/api/v1/schedule"
                        f"?sportId=1&teamId={TEAM_ID}&date={date}"
                    )
                    resp = session.get(url, timeout=STATS_TIMEOUT)
                    resp.raise_for_status()
                    data = resp.json()
                    for d in data.get("dates", []):
                        for game in d.get("games", []):
                            if game.get("status", {}).get("detailedState") != "Final":
                                continue
                            game_pk = game.get("gamePk")
                            if game_pk in self.posted:
                                continue
                            feed_url = (
                                "https://statsapi.mlb.com/api/v1.1/game/"
                                f"{game_pk}/feed/live"
                            )
                            feed = session.get(
                                feed_url, timeout=STATS_TIMEOUT
                            ).json()
                            standings_url = (
                                "https://statsapi.mlb.com/api/v1/standings"
                                f"?leagueId=103&season={datetime.now().year}"
                            )
                            standings = session.get(
                                standings_url, timeout=STATS_TIMEOUT
                            ).json()
                            return self._build_summary(game, feed, standings)
        except Exception as exc:  # pragma: no cover - network
            log.warning("Failed to fetch game summary: %s", exc)
        return None

    def _build_summary(
        self, game: Dict[str, Any], feed: Dict[str, Any], standings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Construct a summary dictionary from API responses."""
        game_pk = game.get("gamePk")
        gd = feed.get("gameData", {})
        ld = feed.get("liveData", {})
        teams = gd.get("teams", {})
        away = teams.get("away", {})
        home = teams.get("home", {})
        mariners_home = home.get("id") == TEAM_ID
        mariners = home if mariners_home else away
        opponent = away if mariners_home else home
        away_abbr = away.get("abbreviation", "")
        home_abbr = home.get("abbreviation", "")
        start_iso = gd.get("datetime", {}).get("dateTime")
        start = (
            datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            if start_iso
            else datetime.now(tz=pytz.utc)
        )
        start_pst = start.astimezone(PST_TZ)
        linescore = ld.get("linescore", {})
        away_score = linescore.get("teams", {}).get("away", {}).get("runs", 0)
        home_score = linescore.get("teams", {}).get("home", {}).get("runs", 0)
        mariners_score = home_score if mariners_home else away_score
        opp_score = away_score if mariners_home else home_score
        # Highlights - brief description + inning
        scoring_indices = ld.get("plays", {}).get("scoringPlays", [])
        all_plays = ld.get("plays", {}).get("allPlays", [])
        highlights: list[str] = []
        for idx in scoring_indices[:3]:
            try:
                play = all_plays[idx]
                desc = play.get("result", {}).get("description", "")
                inning = play.get("about", {}).get("inning")
                half = play.get("about", {}).get("halfInning", "")
                suffix = "th"
                if inning in {1, 21}:
                    suffix = "st"
                elif inning in {2, 22}:
                    suffix = "nd"
                elif inning in {3, 23}:
                    suffix = "rd"
                highlights.append(
                    f"{desc} ({inning}{suffix})"
                )
            except Exception:  # pragma: no cover - defensive
                continue
        # Standings info for record and AL West line
        record_line = ""
        alwest_line = ""
        try:
            def _ordinal(n: str) -> str:
                try:
                    num = int(n)
                except ValueError:
                    return n
                if 10 <= num % 100 <= 20:
                    suffix = "th"
                else:
                    suffix = {1: "st", 2: "nd", 3: "rd"}.get(num % 10, "th")
                return f"{num}{suffix}"

            team_record = None
            leader_abbr = ""
            second_abbr = ""
            second_gb = ""
            for rec in standings.get("records", []):
                teams_rec = rec.get("teamRecords", [])
                if teams_rec:
                    leader_abbr = teams_rec[0].get("team", {}).get("abbreviation", "")
                    if len(teams_rec) > 1:
                        second_abbr = teams_rec[1].get("team", {}).get("abbreviation", "")
                        second_gb = teams_rec[1].get("gamesBack", "")
                for tr in teams_rec:
                    if tr.get("team", {}).get("id") == TEAM_ID:
                        team_record = tr
                        break
                if team_record:
                    break
            if team_record:
                wins = team_record.get("wins", 0)
                losses = team_record.get("losses", 0)
                streak = team_record.get("streak", {}).get("streakCode", "")
                record_line = f"{wins}–{losses} ({streak})"
                div_rank = team_record.get("divisionRank", "")
                gb = team_record.get("gamesBack", "")
                last_ten = next(
                    (
                        f"{sr.get('wins')}–{sr.get('losses')}"
                        for sr in team_record.get("records", {}).get("splitRecords", [])
                        if sr.get("type") == "lastTen"
                    ),
                    "",
                )
                rank_ord = _ordinal(div_rank)
                if div_rank == "1":
                    alwest_line = (
                        f"{rank_ord} • {second_gb} GA of {second_abbr} • Last 10: {last_ten}"
                    )
                else:
                    alwest_line = (
                        f"{rank_ord} • {gb} GB of {leader_abbr} • Last 10: {last_ten}"
                    )
        except Exception:  # pragma: no cover - defensive
            pass
        # Top performers: simple hitter and pitcher selection
        top_perf: Dict[str, str] = {}
        for key, team in ("home", home), ("away", away):
            players = ld.get("boxscore", {}).get("teams", {}).get(key, {}).get(
                "players", {}
            )
            hitter = None
            pitcher = None
            for p in players.values():
                stats = p.get("stats", {})
                bat = stats.get("batting", {})
                pit = stats.get("pitching", {})
                if bat.get("atBats", 0) > 0:
                    if not hitter or bat.get("hits", 0) > hitter.get("stats", {}).get("batting", {}).get("hits", 0):
                        hitter = p
                if pit.get("inningsPitched") and pit.get("outs", 0) > 0:
                    if not pitcher or pit.get("outs", 0) > pitcher.get("stats", {}).get("pitching", {}).get("outs", 0):
                        pitcher = p
            def _fmt_line(player: Dict[str, Any]) -> str:
                if not player:
                    return ""
                info = player.get("person", {}).get("fullName", "")
                bat = player.get("stats", {}).get("batting", {})
                pit = player.get("stats", {}).get("pitching", {})
                if bat.get("atBats", 0) > 0:
                    line = f"{bat.get('hits',0)}-{bat.get('atBats',0)}"
                    if bat.get("homeRuns", 0):
                        line += f", HR ({bat.get('homeRuns')})"
                    if bat.get("rbi", 0):
                        line += f", {bat.get('rbi')} RBI"
                else:
                    line = (
                        f"{pit.get('inningsPitched','0.0')} IP, {pit.get('strikeOuts',0)} K, {pit.get('earnedRuns',0)} ER"
                    )
                return f"{info}: {line}"
            parts = []
            if hitter:
                parts.append(_fmt_line(hitter))
            if pitcher:
                parts.append(_fmt_line(pitcher))
            abbr = team.get("abbreviation", "")
            top_perf[abbr] = " | ".join(parts)
        summary = {
            "game_pk": game_pk,
            "mariners_home": mariners_home,
            "away_abbr": away_abbr,
            "home_abbr": home_abbr,
            "mariners_score": mariners_score,
            "opp_score": opp_score,
            "opp_name": opponent.get("teamName", "Opponent"),
            "opp_abbr": opponent.get("abbreviation", ""),
            "start_pst": start_pst,
            "highlights": highlights,
            "record": record_line,
            "al_west": alwest_line,
            "top_performers": top_perf,
        }
        return summary

    def build_message(self, summary: Dict[str, Any]) -> str:
        """Format the game summary into a Discord message."""
        start_fmt = summary["start_pst"].strftime("%a %b %d, %-I:%M %p PT")
        header = f"{summary['away_abbr']} @ {summary['home_abbr']}"
        top_header = f"⚾️ **{header} — {start_fmt}**"
        final_line = (
            f"*Final*: Mariners {summary['mariners_score']} — {summary['opp_name']} {summary['opp_score']}"
        )
        highlights_line = (
            "*Highlights*: " + "; ".join(summary.get("highlights", []))
            if summary.get("highlights")
            else ""
        )
        record_line = f"*Record*: {summary.get('record', '')}"
        al_line = f"*AL West*: {summary.get('al_west', '')}"
        lines = [top_header, final_line]
        if highlights_line:
            lines.append(highlights_line)
        lines.extend([record_line, al_line, "", "*Top Performers*"])
        sea_perf = summary.get("top_performers", {}).get("SEA", "")
        opp_perf = summary.get("top_performers", {}).get(summary.get("opp_abbr", ""), "")
        lines.append(f"SEA — {sea_perf}")
        lines.append(f"{summary.get('opp_abbr','')} — {opp_perf}")
        return "\n".join(lines)

    # ---------------------------------------------------------------- background
    @tasks.loop(minutes=10)
    async def game_task(self) -> None:
        await self.bot.wait_until_ready()
        summary = await asyncio.to_thread(self.fetch_game_summary)
        if not summary:
            return
        gid = summary.get("game_pk")
        if gid in self.posted:
            return
        channel = self.bot.get_channel(getattr(cfg, "SPORTS_CHANNEL_ID", 0))
        if not isinstance(channel, discord.TextChannel):
            log.error("Sports channel not found")
            self.posted.add(gid)
            await self._save_posted(gid)
            return
        try:
            msg = self.build_message(summary)
            await channel.send(msg)
            self.posted.add(gid)
            await self._save_posted(gid)
        except Exception as exc:  # pragma: no cover - network
            log.exception("Failed to post game summary: %s", exc)


async def setup(bot: commands.Bot) -> None:  # pragma: no cover - entry point
    await bot.add_cog(MarinersGameCog(bot))
