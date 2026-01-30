"""Mariners game day companion with threads, live updates, and summaries.

Features:
  - Auto-creates game threads 1 hour before game time
  - Posts live inning-by-inning score updates during games
  - Posts detailed post-game summaries with stats
  - Surfaces /bigdumper command for Cal Raleigh tracker
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Awaitable, Dict, Iterable, List, Optional, Tuple

import asyncio
import asyncpg
import pytz
import requests
from dateutil import parser
from requests.adapters import HTTPAdapter, Retry

import discord
from discord.ext import commands, tasks

from .sports_cog import PST_TZ, STATS_TIMEOUT, TEAM_ID
from .. import bot_config as cfg
from ..db import get_pool

log = logging.getLogger(f"gentlebot.{__name__}")

ESPN_SCHEDULE_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams/sea/schedule"
)
ESPN_SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary"
)
DIVISION_GROUP_ID = 3
TEAM_ABBR = "SEA"

STATS_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=136"
STATS_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
STATS_STANDINGS_URL = (
    "https://statsapi.mlb.com/api/v1/standings?leagueId=103&season={season}&standingsType=byDivision"
)


class _ImmediateResult:
    """Awaitable wrapper returning a precomputed summary result."""

    def __init__(self, result: Optional[Dict[str, Any]]):
        self._result = result

    def __await__(self):
        async def _runner() -> Optional[Dict[str, Any]]:
            return self._result

        return _runner().__await__()


class MarinersGameCog(commands.Cog):
    """Game day companion with threads, live updates, and summaries."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.posted: set[str] = set()
        self.pool: asyncpg.Pool | None = None
        self.tracking_since: datetime = datetime.now(tz=pytz.utc)
        # Track game threads and live updates
        self.threads: Dict[str, discord.Thread] = {}
        self.threads_opened: set[str] = set()
        self.innings_posted: Dict[str, int] = {}  # game_id -> last inning posted

    async def cog_load(self) -> None:  # pragma: no cover - startup
        try:
            pool = await get_pool()
            self.pool = pool
            await self._ensure_table()
            await self._ensure_tracking_state()
        except Exception as exc:  # pragma: no cover - database init
            self.pool = None
            log.warning(
                "MarinersGameCog disabled database persistence: %s", exc
            )
        # Load posted state even if other init fails (uses existing pool if available)
        if self.pool:
            try:
                await self._load_posted()
            except Exception as exc:
                log.warning("Failed to load posted state: %s", exc)
            try:
                await self._sync_schedule()
            except Exception as exc:
                log.warning("Failed to sync schedule: %s", exc)
        self.game_task.start()
        self.thread_task.start()
        self.live_score_task.start()

    async def cog_unload(self) -> None:  # pragma: no cover - cleanup
        self.game_task.cancel()
        self.thread_task.cancel()
        self.live_score_task.cancel()

    # ------------------------------------------------------------------ helpers
    async def _ensure_table(self) -> None:
        if not self.pool:
            return
        await self.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS mariners_schedule (
                event_id TEXT PRIMARY KEY,
                season_year INTEGER NOT NULL,
                game_date TIMESTAMPTZ NOT NULL,
                home_away TEXT NOT NULL,
                opponent_abbr TEXT NOT NULL,
                opponent_name TEXT NOT NULL,
                venue TEXT,
                short_name TEXT,
                state TEXT NOT NULL DEFAULT 'pre',
                mariners_score INTEGER,
                opponent_score INTEGER,
                summary JSONB,
                message_id BIGINT,
                message_posted_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await self.pool.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_mariners_schedule_season
            ON mariners_schedule (season_year, game_date)
            """
        )
        await self.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS mariners_schedule_state (
                id INTEGER PRIMARY KEY,
                tracking_since TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

    async def _ensure_tracking_state(self) -> None:
        if not self.pool:
            return
        try:
            row = await self.pool.fetchrow(
                "SELECT tracking_since FROM mariners_schedule_state WHERE id = 1"
            )
        except Exception as exc:  # pragma: no cover - database
            log.warning("Failed to load Mariners tracking state: %s", exc)
            return
        if row:
            tracking = row["tracking_since"]
            if isinstance(tracking, datetime):
                if tracking.tzinfo is None:
                    tracking = pytz.utc.localize(tracking)
                self.tracking_since = tracking
            return
        now_utc = datetime.now(tz=pytz.utc)
        try:
            await self.pool.execute(
                """
                INSERT INTO mariners_schedule_state (id, tracking_since)
                VALUES (1, $1)
                ON CONFLICT (id) DO NOTHING
                """,
                now_utc,
            )
        except Exception as exc:  # pragma: no cover - database
            log.warning("Failed to initialize Mariners tracking state: %s", exc)
            return
        self.tracking_since = now_utc

    async def _load_posted(self) -> None:
        if not self.pool:
            return
        rows = await self.pool.fetch(
            "SELECT event_id FROM mariners_schedule WHERE message_id IS NOT NULL"
        )
        self.posted.update(str(r[0]) for r in rows)

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    async def _sync_schedule(self) -> None:
        if not self.pool:
            return
        schedule = await asyncio.to_thread(self._fetch_schedule)
        if not schedule:
            return
        for row in schedule:
            game_date = row.get("game_date")
            if isinstance(game_date, datetime):
                if game_date.tzinfo is None:
                    game_date = pytz.utc.localize(game_date)
            else:
                continue
            if game_date < self.tracking_since:
                continue
            try:
                await self.pool.execute(
                    """
                    INSERT INTO mariners_schedule (
                        event_id,
                        season_year,
                        game_date,
                        home_away,
                        opponent_abbr,
                        opponent_name,
                        venue,
                        short_name,
                        state,
                        mariners_score,
                        opponent_score,
                        updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now()
                    )
                    ON CONFLICT (event_id) DO UPDATE SET
                        season_year = EXCLUDED.season_year,
                        game_date = EXCLUDED.game_date,
                        home_away = EXCLUDED.home_away,
                        opponent_abbr = EXCLUDED.opponent_abbr,
                        opponent_name = EXCLUDED.opponent_name,
                        venue = EXCLUDED.venue,
                        short_name = EXCLUDED.short_name,
                        state = EXCLUDED.state,
                        mariners_score = EXCLUDED.mariners_score,
                        opponent_score = EXCLUDED.opponent_score,
                        updated_at = now()
                    """,
                    row["event_id"],
                    row["season_year"],
                    game_date,
                    row["home_away"],
                    row["opponent_abbr"],
                    row["opponent_name"],
                    row["venue"],
                    row["short_name"],
                    row["state"],
                    row["mariners_score"],
                    row["opponent_score"],
                )
            except Exception as exc:  # pragma: no cover - database
                log.warning("Failed to upsert Mariners schedule %s: %s", row["event_id"], exc)

    def _fetch_schedule(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            with self._build_session() as session:
                resp = session.get(ESPN_SCHEDULE_URL, timeout=STATS_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # pragma: no cover - network
            log.warning("Failed to fetch Mariners schedule: %s", exc)
            return rows
        for event in data.get("events", []):
            competitions = event.get("competitions", [])
            if not competitions:
                continue
            comp = competitions[0]
            competitors = comp.get("competitors", [])
            try:
                sea_comp = next(
                    c for c in competitors if c.get("team", {}).get("abbreviation") == TEAM_ABBR
                )
                opp_comp = next(c for c in competitors if c is not sea_comp)
            except StopIteration:
                continue
            try:
                start = parser.isoparse(comp.get("date"))
            except (TypeError, ValueError):
                start = datetime.now(tz=pytz.utc)
            state = comp.get("status", {}).get("type", {}).get("state", "pre")
            mariners_score = (
                int(float(sea_comp.get("score", "0"))) if state == "post" else None
            )
            opponent_score = (
                int(float(opp_comp.get("score", "0"))) if state == "post" else None
            )
            rows.append(
                {
                    "event_id": str(event.get("id")),
                    "season_year": event.get("season", {}).get("year", start.year),
                    "game_date": start,
                    "home_away": sea_comp.get("homeAway", "home"),
                    "opponent_abbr": opp_comp.get("team", {}).get("abbreviation", ""),
                    "opponent_name": opp_comp.get("team", {}).get("displayName", "Opponent"),
                    "venue": comp.get("venue", {}).get("fullName", ""),
                    "short_name": event.get("shortName", ""),
                    "state": state,
                    "mariners_score": mariners_score,
                    "opponent_score": opponent_score,
                }
            )
        return rows

    def _serialize_summary(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(summary)
        start = payload.get("start_pst")
        if isinstance(start, datetime):
            payload["start_pst"] = start.isoformat()
        return payload

    def _deserialize_summary(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(summary)
        start = payload.get("start_pst")
        if isinstance(start, str):
            try:
                payload["start_pst"] = datetime.fromisoformat(start)
            except ValueError:
                payload["start_pst"] = datetime.now(tz=PST_TZ)
        return payload

    async def _mark_posted(self, event_id: str, message_id: Optional[int]) -> None:
        if not self.pool:
            return
        try:
            await self.pool.execute(
                """
                UPDATE mariners_schedule
                SET message_id = $1,
                    message_posted_at = now(),
                    updated_at = now()
                WHERE event_id = $2
                """,
                message_id,
                event_id,
            )
        except Exception as exc:  # pragma: no cover - database
            log.warning("Failed to record Mariners post %s: %s", event_id, exc)

    async def _fetch_game_summary_db(self) -> Optional[Dict[str, Any]]:
        if not self.pool:
            return None
        try:
            await self._sync_schedule()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Failed to refresh Mariners schedule: %s", exc)
        row = await self.pool.fetchrow(
            """
            SELECT event_id,
                   summary,
                   mariners_score,
                   opponent_score,
                   home_away,
                   opponent_abbr,
                   opponent_name,
                   game_date,
                   season_year,
                   short_name
            FROM mariners_schedule
            WHERE state = 'post'
              AND message_id IS NULL
              AND game_date >= $1
            ORDER BY game_date DESC
            LIMIT 1
            """,
            self.tracking_since,
        )
        if not row:
            return None
        event_id = str(row["event_id"])
        summary = row["summary"]
        if summary:
            data = self._deserialize_summary(summary)
            data.setdefault("event_id", event_id)
            return data
        data = await asyncio.to_thread(self._build_summary_from_event, event_id, dict(row))
        if not data:
            return None
        try:
            await self.pool.execute(
                """
                UPDATE mariners_schedule
                SET summary = $1,
                    mariners_score = $2,
                    opponent_score = $3,
                    updated_at = now()
                WHERE event_id = $4
                """,
                self._serialize_summary(data),
                data.get("mariners_score"),
                data.get("opp_score"),
                event_id,
            )
        except Exception as exc:  # pragma: no cover - database
            log.warning("Failed to store Mariners summary %s: %s", event_id, exc)
        return data

    def _latest_stats_game(self, schedule: dict[str, Any]) -> Optional[dict[str, Any]]:
        latest: tuple[datetime, dict[str, Any]] | None = None
        for day in schedule.get("dates", []):
            games = day.get("games", []) or []
            for game in games:
                status = (game.get("status") or {}).get("detailedState", "")
                if status not in {"Final", "Game Over", "Completed"}:
                    continue
                teams = game.get("teams", {})
                home_team = (teams.get("home") or {}).get("team") or {}
                away_team = (teams.get("away") or {}).get("team") or {}
                if home_team.get("id") == TEAM_ID:
                    mariners_home = True
                elif away_team.get("id") == TEAM_ID:
                    mariners_home = False
                else:
                    continue
                pk = str(game.get("gamePk") or "")
                if not pk:
                    continue
                season = game.get("season")
                try:
                    start_raw = game.get("gameDate")
                    start = parser.isoparse(start_raw) if start_raw else datetime.now(tz=pytz.utc)
                except Exception:
                    start = datetime.now(tz=pytz.utc)
                info = {
                    "game_pk": pk,
                    "mariners_home": mariners_home,
                    "season": int(season) if season else start.year,
                }
                if latest is None or start >= latest[0]:
                    latest = (start, info)
        return latest[1] if latest else None

    def _collect_stats_highlights(self, plays: Iterable[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for play in plays:
            result = play.get("result", {})
            description = result.get("description")
            if not description:
                continue
            about = play.get("about", {})
            inning = about.get("inning")
            half = about.get("halfInning", "")
            if inning is not None:
                inning_text = self._ordinal(inning)
                half_text = half.title() if isinstance(half, str) else ""
                if half_text:
                    description = f"{description} ({half_text} {inning_text})"
                else:
                    description = f"{description} ({inning_text})"
            lines.append(description)
            if len(lines) == 3:
                break
        return lines

    def _build_stats_summary(
        self,
        feed: Dict[str, Any],
        standings: Dict[str, Any],
        mariners_home: bool,
        game_pk: str,
    ) -> Optional[Dict[str, Any]]:
        teams = feed.get("gameData", {}).get("teams", {})
        home_team = teams.get("home", {})
        away_team = teams.get("away", {})
        if not home_team or not away_team:
            return None
        mariners_team = home_team if mariners_home else away_team
        opponent_team = away_team if mariners_home else home_team
        away_abbr = away_team.get("abbreviation", "")
        home_abbr = home_team.get("abbreviation", "")
        opponent_abbr = opponent_team.get("abbreviation") or opponent_team.get("teamName", "")
        opponent_name = (
            opponent_team.get("teamName")
            or opponent_team.get("name")
            or opponent_abbr
            or "Opponent"
        )
        dt_iso = feed.get("gameData", {}).get("datetime", {}).get("dateTime")
        try:
            start_dt = parser.isoparse(dt_iso) if dt_iso else datetime.now(tz=pytz.utc)
        except Exception:
            start_dt = datetime.now(tz=pytz.utc)
        start_pst = start_dt.astimezone(PST_TZ)
        linescore = feed.get("liveData", {}).get("linescore", {}).get("teams", {})
        mariners_runs = self._to_int(linescore.get("home" if mariners_home else "away", {}).get("runs"))
        opponent_runs = self._to_int(linescore.get("away" if mariners_home else "home", {}).get("runs"))
        highlights = self._collect_stats_highlights(
            feed.get("liveData", {}).get("plays", {}).get("scoringPlays", [])
        )
        record_line = ""
        al_west_line = ""
        try:
            record_entry = next(
                (
                    rec
                    for group in standings.get("records", [])
                    for rec in group.get("teamRecords", [])
                    if rec.get("team", {}).get("id") == TEAM_ID
                    or rec.get("team", {}).get("abbreviation") == TEAM_ABBR
                ),
                None,
            )
        except Exception:
            record_entry = None
        if record_entry:
            wins = record_entry.get("wins")
            losses = record_entry.get("losses")
            if wins is not None and losses is not None:
                record_line = f"{wins}-{losses}"
            streak_code = (record_entry.get("streak") or {}).get("streakCode")
            if streak_code:
                record_line = f"{record_line} ({streak_code})" if record_line else streak_code
            games_back = record_entry.get("gamesBack")
            if games_back in (0, 0.0, "0", "0.0"):
                gb_piece = "0.0 GB"
            elif games_back:
                gb_piece = f"{games_back} GB"
            else:
                gb_piece = ""
            rank_val = record_entry.get("divisionRank")
            rank_piece = self._ordinal(rank_val) if rank_val else ""
            last_ten_piece = ""
            splits = (record_entry.get("records") or {}).get("splitRecords", [])
            for split in splits:
                if split.get("type") == "lastTen":
                    wins_lt = split.get("wins")
                    losses_lt = split.get("losses")
                    if wins_lt is not None and losses_lt is not None:
                        last_ten_piece = f"Last 10: {wins_lt}-{losses_lt}"
                    break
            pieces = [piece for piece in (rank_piece, gb_piece, last_ten_piece) if piece]
            al_west_line = " • ".join(pieces)
        performers = {
            TEAM_ABBR: "",
            opponent_abbr or opponent_name: "",
        }
        return {
            "event_id": game_pk,
            "mariners_home": mariners_home,
            "away_abbr": away_abbr,
            "home_abbr": home_abbr,
            "mariners_score": mariners_runs,
            "opp_score": opponent_runs,
            "opp_name": opponent_name,
            "opp_abbr": opponent_abbr or opponent_name,
            "start_pst": start_pst,
            "highlights": highlights,
            "record": record_line,
            "al_west": al_west_line,
            "top_performers": performers,
        }

    def _fetch_summary_without_db(self) -> Optional[Dict[str, Any]]:
        try:
            with self._build_session() as session:
                schedule_data = session.get(STATS_SCHEDULE_URL, timeout=STATS_TIMEOUT).json()
                latest = self._latest_stats_game(schedule_data)
                if not latest:
                    return None
                game_pk = latest["game_pk"]
                mariners_home = latest["mariners_home"]
                season_year = latest.get("season")
                feed_data = session.get(
                    STATS_FEED_URL.format(game_pk=game_pk), timeout=STATS_TIMEOUT
                ).json()
                if not season_year:
                    dt_iso = feed_data.get("gameData", {}).get("datetime", {}).get("dateTime")
                    if dt_iso:
                        try:
                            season_year = parser.isoparse(dt_iso).year
                        except Exception:
                            season_year = datetime.now(tz=pytz.utc).year
                    else:
                        season_year = datetime.now(tz=pytz.utc).year
                standings_data = session.get(
                    STATS_STANDINGS_URL.format(season=season_year), timeout=STATS_TIMEOUT
                ).json()
        except Exception as exc:
            log.warning("Failed to build Mariners summary without database: %s", exc)
            return None
        return self._build_stats_summary(feed_data, standings_data, mariners_home, game_pk)

    def fetch_game_summary(self) -> Awaitable[Optional[Dict[str, Any]]]:
        if not self.pool:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return _ImmediateResult(self._fetch_summary_without_db())
            return asyncio.to_thread(self._fetch_summary_without_db)
        return self._fetch_game_summary_db()

    def _build_summary_from_event(
        self, event_id: str, row: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            with self._build_session() as session:
                summary_resp = session.get(
                    ESPN_SUMMARY_URL,
                    params={"event": event_id, "region": "us", "lang": "en"},
                    timeout=STATS_TIMEOUT,
                )
                summary_resp.raise_for_status()
                summary = summary_resp.json()
                comp = summary.get("header", {}).get("competitions", [{}])[0]
                competitors = comp.get("competitors", [])
                sea_comp = next(
                    c for c in competitors if c.get("team", {}).get("abbreviation") == TEAM_ABBR
                )
                opp_comp = next(c for c in competitors if c is not sea_comp)
                away_comp = next(
                    c for c in competitors if c.get("homeAway") == "away"
                )
                home_comp = next(
                    c for c in competitors if c.get("homeAway") == "home"
                )
                start = parser.isoparse(comp.get("date"))
                start_pst = start.astimezone(PST_TZ)
                mariners_home = sea_comp is home_comp
                mariners_score = int(float(sea_comp.get("score", "0")))
                opp_score = int(float(opp_comp.get("score", "0")))
                away_abbr = away_comp.get("team", {}).get("abbreviation", "")
                home_abbr = home_comp.get("team", {}).get("abbreviation", "")
                highlights = self._collect_highlights(summary.get("plays", []))
                season_year = row.get("season_year", start.year)
                record_info = self._fetch_record_info(session, season_year)
                standings = self._fetch_division_standings(session, season_year)
                record_line = record_info["summary"]
                if record_info["streak"]:
                    record_line = f"{record_line} ({record_info['streak']})" if record_line else record_info["streak"]
                al_west_line = self._format_division_line(standings, record_info["last_ten"])
                performers = self._top_performers(summary.get("boxscore", {}), opp_comp)
        except Exception as exc:  # pragma: no cover - network parsing
            log.warning("Failed to build Mariners summary for %s: %s", event_id, exc)
            return None
        return {
            "event_id": event_id,
            "mariners_home": mariners_home,
            "away_abbr": away_abbr,
            "home_abbr": home_abbr,
            "mariners_score": mariners_score,
            "opp_score": opp_score,
            "opp_name": opp_comp.get("team", {}).get("displayName", "Opponent"),
            "opp_abbr": opp_comp.get("team", {}).get("abbreviation", ""),
            "start_pst": start_pst,
            "highlights": highlights,
            "record": record_line,
            "al_west": al_west_line,
            "top_performers": performers,
        }

    def _collect_highlights(self, plays: Iterable[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for play in plays:
            if not play.get("scoringPlay"):
                continue
            text = play.get("text", "")
            period = play.get("period", {})
            inning = period.get("number")
            half = period.get("type", "")
            if inning:
                text = f"{text} ({half.title()} {self._ordinal(inning)})"
            lines.append(text)
            if len(lines) == 3:
                break
        return lines

    def _ordinal(self, value: int) -> str:
        try:
            num = int(value)
        except (TypeError, ValueError):
            return str(value)
        if 10 <= num % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(num % 10, "th")
        return f"{num}{suffix}"

    def _fetch_record_info(self, session: requests.Session, season_year: int) -> dict[str, str]:
        info = {"summary": "", "streak": "", "last_ten": ""}
        try:
            team = session.get(
                f"https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/seasons/{season_year}/teams/sea",
                params={"lang": "en", "region": "us"},
                timeout=STATS_TIMEOUT,
            ).json()
            record = session.get(team["record"]["$ref"], timeout=STATS_TIMEOUT).json()
            total = next((item for item in record.get("items", []) if item.get("type") == "total"), None)
            last_ten = next(
                (item for item in record.get("items", []) if item.get("type") == "lasttengames"),
                None,
            )
            if total:
                info["summary"] = total.get("summary", "")
                stats = {s["name"]: s.get("displayValue") or s.get("value") for s in total.get("stats", [])}
                info["streak"] = stats.get("streak", "") or ""
            if last_ten:
                info["last_ten"] = last_ten.get("summary", "")
        except Exception:  # pragma: no cover - defensive
            pass
        return info

    def _fetch_division_standings(
        self, session: requests.Session, season_year: int
    ) -> list[dict[str, str]]:
        teams: list[dict[str, str]] = []
        try:
            group = session.get(
                f"http://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/seasons/{season_year}/types/2/groups/{DIVISION_GROUP_ID}",
                params={"lang": "en", "region": "us"},
                timeout=STATS_TIMEOUT,
            ).json()
            standings = session.get(group["standings"]["$ref"], timeout=STATS_TIMEOUT).json()
            overall_ref = None
            for item in standings.get("items", []):
                if item.get("name") == "overall":
                    overall_ref = item.get("$ref")
                    break
            if not overall_ref:
                return teams
            overall = session.get(overall_ref, timeout=STATS_TIMEOUT).json()
            for team_entry in overall.get("standings", []):
                team_info = session.get(team_entry["team"]["$ref"], timeout=STATS_TIMEOUT).json()
                total = next(
                    (rec for rec in team_entry.get("records", []) if rec.get("type") == "total"),
                    None,
                )
                stats = (
                    {s["name"]: s.get("displayValue") or s.get("value") for s in total.get("stats", [])}
                    if total
                    else {}
                )
                teams.append(
                    {
                        "abbr": team_info.get("abbreviation", ""),
                        "gamesBehind": stats.get("gamesBehind", ""),
                    }
                )
        except Exception:  # pragma: no cover - defensive
            return teams
        return teams

    def _format_division_line(
        self, standings: list[dict[str, str]], last_ten: str
    ) -> str:
        if not standings:
            return f"Last 10: {last_ten}" if last_ten else ""
        try:
            sea_index = next(i for i, entry in enumerate(standings) if entry.get("abbr") == TEAM_ABBR)
        except StopIteration:
            return f"Last 10: {last_ten}" if last_ten else ""
        rank = sea_index + 1
        ordinal_rank = self._ordinal(rank)
        if rank == 1 and len(standings) > 1:
            ga = standings[1].get("gamesBehind", "0")
            parts = [ordinal_rank, f"{ga} GA of {standings[1].get('abbr', '')}"]
        elif standings:
            leader = standings[0]
            gb = standings[sea_index].get("gamesBehind", "")
            parts = [ordinal_rank, f"{gb} GB of {leader.get('abbr', '')}"]
        else:
            parts = [ordinal_rank]
        if last_ten:
            parts.append(f"Last 10: {last_ten}")
        return " • ".join(part for part in parts if part)

    def _top_performers(
        self, boxscore: Dict[str, Any], opponent_comp: Dict[str, Any]
    ) -> Dict[str, str]:
        performers: Dict[str, str] = {}
        players = {entry.get("team", {}).get("abbreviation", ""): entry for entry in boxscore.get("players", [])}
        sea_entry = players.get(TEAM_ABBR)
        opp_abbr = opponent_comp.get("team", {}).get("abbreviation", "")
        opp_entry = players.get(opp_abbr)
        if sea_entry:
            performers[TEAM_ABBR] = self._format_team_performers(sea_entry)
        if opp_abbr and opp_entry:
            performers[opp_abbr] = self._format_team_performers(opp_entry)
        return performers

    def _format_team_performers(self, entry: Dict[str, Any]) -> str:
        batting = next(
            (stat for stat in entry.get("statistics", []) if stat.get("type") == "batting"),
            None,
        )
        pitching = next(
            (stat for stat in entry.get("statistics", []) if stat.get("type") == "pitching"),
            None,
        )
        parts: list[str] = []
        hitter = self._select_hitter(batting) if batting else ""
        pitcher = self._select_pitcher(pitching) if pitching else ""
        if hitter:
            parts.append(hitter)
        if pitcher:
            parts.append(pitcher)
        return " | ".join(parts)

    def _select_hitter(self, stat: Dict[str, Any]) -> str:
        keys = stat.get("keys", [])
        best: tuple[str, str, int, int] | None = None
        best_hits = -1
        best_rbi = -1
        for athlete in stat.get("athletes", []):
            stats = athlete.get("stats", [])
            data = {keys[i]: stats[i] for i in range(min(len(keys), len(stats)))}
            hits = self._to_int(data.get("hits"))
            at_bats = self._to_int(data.get("atBats"))
            rbi = self._to_int(data.get("RBIs"))
            hr = self._to_int(data.get("homeRuns"))
            if at_bats == 0 and hits == 0 and rbi == 0 and hr == 0:
                continue
            if hits > best_hits or (hits == best_hits and rbi > best_rbi):
                best = (
                    athlete.get("athlete", {}).get("displayName", ""),
                    data.get("hits-atBats", ""),
                    hr,
                    rbi,
                )
                best_hits = hits
                best_rbi = rbi
        if not best:
            return ""
        name, slash, hr, rbi = best
        line = slash
        if hr:
            line += f", HR ({hr})"
        if rbi:
            line += f", {rbi} RBI"
        return f"{name}: {line}"

    def _select_pitcher(self, stat: Dict[str, Any]) -> str:
        keys = stat.get("keys", [])
        best: tuple[str, str, int, int] | None = None
        best_outs = -1
        best_ks = -1
        for athlete in stat.get("athletes", []):
            stats = athlete.get("stats", [])
            data = {keys[i]: stats[i] for i in range(min(len(keys), len(stats)))}
            ip = data.get("fullInnings.partInnings", "0.0")
            outs = self._outs_from_ip(ip)
            strikeouts = self._to_int(data.get("strikeouts"))
            er = self._to_int(data.get("earnedRuns"))
            if outs == 0 and strikeouts == 0:
                continue
            if outs > best_outs or (outs == best_outs and strikeouts > best_ks):
                best = (
                    athlete.get("athlete", {}).get("displayName", ""),
                    ip,
                    strikeouts,
                    er,
                )
                best_outs = outs
                best_ks = strikeouts
        if not best:
            return ""
        name, ip, strikeouts, er = best
        return f"{name}: {ip} IP, {strikeouts} K, {er} ER"

    def _outs_from_ip(self, value: Optional[str]) -> int:
        if not value:
            return 0
        try:
            if "." in value:
                whole, frac = value.split(".", 1)
                outs = int(whole) * 3 + int(frac)
            else:
                outs = int(value) * 3
            return outs
        except ValueError:
            return 0

    def _to_int(self, value: Any) -> int:
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            return 0

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
        sea_perf = summary.get("top_performers", {}).get(TEAM_ABBR, "")
        opp_perf = summary.get("top_performers", {}).get(summary.get("opp_abbr", ""), "")
        lines.append(f"{TEAM_ABBR} — {sea_perf}")
        lines.append(f"{summary.get('opp_abbr','')} — {opp_perf}")
        return "\n".join(lines)

    # ---------------------------------------------------------------- thread helpers
    def _fetch_upcoming_games(self) -> List[Dict[str, Any]]:
        """Fetch upcoming Mariners games for thread creation."""
        games: List[Dict[str, Any]] = []
        try:
            with self._build_session() as session:
                resp = session.get(ESPN_SCHEDULE_URL, timeout=STATS_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            log.warning("Failed to fetch Mariners schedule: %s", exc)
            return games

        for event in data.get("events", []):
            competitions = event.get("competitions", [])
            if not competitions:
                continue
            comp = competitions[0]
            state = comp.get("status", {}).get("type", {}).get("state", "pre")
            if state == "post":
                continue  # Skip finished games

            try:
                start = parser.isoparse(comp.get("date"))
                if start.tzinfo is None:
                    start = pytz.utc.localize(start)
            except (TypeError, ValueError):
                continue

            competitors = comp.get("competitors", [])
            try:
                sea_comp = next(
                    c for c in competitors if c.get("team", {}).get("abbreviation") == TEAM_ABBR
                )
                opp_comp = next(c for c in competitors if c is not sea_comp)
            except StopIteration:
                continue

            games.append({
                "id": str(event.get("id")),
                "start": start,
                "opponent": opp_comp.get("team", {}).get("displayName", "Opponent"),
                "opp_abbr": opp_comp.get("team", {}).get("abbreviation", "OPP"),
                "home_away": sea_comp.get("homeAway", "home"),
                "short_name": event.get("shortName", ""),
                "state": state,
            })

        return games

    def _thread_title(self, game: Dict[str, Any]) -> str:
        """Generate thread title for a game."""
        start_pst = game["start"].astimezone(PST_TZ)
        time_str = start_pst.strftime("%-m/%-d, %-I:%M%p").lower()
        return f"⚾ {game['short_name']} ({time_str} PT)"

    def _thread_opening_message(self, game: Dict[str, Any]) -> str:
        """Generate the opening message for a game thread."""
        start_pst = game["start"].astimezone(PST_TZ)
        lines = [
            f"## ⚾ Mariners vs {game['opponent']}",
            f"**First Pitch:** {start_pst.strftime('%I:%M %p PT')}",
            "",
            "Live inning updates will be posted here!",
            "",
            "💪 Track Cal Raleigh's homer count with `/bigdumper`",
        ]
        return "\n".join(lines)

    def _fetch_live_linescore(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Fetch live linescore for an in-progress game."""
        try:
            with self._build_session() as session:
                resp = session.get(
                    ESPN_SUMMARY_URL,
                    params={"event": game_id, "region": "us", "lang": "en"},
                    timeout=STATS_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            log.warning("Failed to fetch live score for %s: %s", game_id, exc)
            return None

        try:
            comp = data.get("header", {}).get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            sea_comp = next(
                c for c in competitors if c.get("team", {}).get("abbreviation") == TEAM_ABBR
            )
            opp_comp = next(c for c in competitors if c is not sea_comp)

            status = comp.get("status", {})
            period = status.get("period", 0)
            state = status.get("type", {}).get("state", "pre")
            detail = status.get("type", {}).get("shortDetail", "")

            sea_score = int(float(sea_comp.get("score", "0") or "0"))
            opp_score = int(float(opp_comp.get("score", "0") or "0"))

            return {
                "inning": period,
                "state": state,
                "detail": detail,
                "sea_score": sea_score,
                "opp_score": opp_score,
                "opp_abbr": opp_comp.get("team", {}).get("abbreviation", "OPP"),
            }
        except Exception as exc:
            log.warning("Failed to parse live score for %s: %s", game_id, exc)
            return None

    async def _open_game_threads(self) -> None:
        """Create game threads 1 hour before game time."""
        now = datetime.now(tz=pytz.utc)

        try:
            games = await asyncio.to_thread(self._fetch_upcoming_games)
        except Exception:
            log.exception("Failed to fetch upcoming Mariners games")
            return

        for game in games:
            gid = game["id"]
            if gid in self.threads_opened:
                continue

            # Open thread 1 hour before game
            open_time = game["start"] - timedelta(hours=1)
            if not (open_time <= now < game["start"]):
                continue

            channel = self.bot.get_channel(getattr(cfg, "SPORTS_CHANNEL_ID", 0))
            if not isinstance(channel, discord.TextChannel):
                log.error("Sports channel not found for Mariners thread")
                self.threads_opened.add(gid)
                continue

            title = self._thread_title(game)
            try:
                thread = await channel.create_thread(
                    name=title,
                    auto_archive_duration=1440,
                    type=discord.ChannelType.public_thread,
                )
                opening_msg = self._thread_opening_message(game)
                await thread.send(opening_msg)
                self.threads[gid] = thread
                self.threads_opened.add(gid)
                self.innings_posted[gid] = 0
                log.info("Created Mariners game thread: %s", title)
            except Exception:
                log.exception("Failed to create Mariners thread %s", title)

    async def _update_live_scores(self) -> None:
        """Post inning-by-inning score updates to active threads."""
        for gid, thread in list(self.threads.items()):
            try:
                score = await asyncio.to_thread(self._fetch_live_linescore, gid)
            except Exception:
                log.exception("Failed to fetch live score for %s", gid)
                continue

            if not score:
                continue

            current_inning = score.get("inning", 0)
            last_posted = self.innings_posted.get(gid, 0)
            state = score.get("state", "pre")

            # Post update when inning changes
            if current_inning > last_posted and state == "in":
                sea_score = score.get("sea_score", 0)
                opp_score = score.get("opp_score", 0)
                opp_abbr = score.get("opp_abbr", "OPP")
                detail = score.get("detail", f"Inning {current_inning}")

                msg = f"**{detail}**: Mariners {sea_score} — {opp_abbr} {opp_score}"
                try:
                    await thread.send(msg)
                    self.innings_posted[gid] = current_inning
                except Exception:
                    log.exception("Failed to send inning update for %s", gid)

            # Clean up finished games from active tracking
            if state == "post":
                # Remove from active threads but keep in threads_opened
                self.threads.pop(gid, None)
                self.innings_posted.pop(gid, None)

    # ---------------------------------------------------------------- background tasks
    @tasks.loop(minutes=30)
    async def thread_task(self) -> None:
        """Check for games starting soon and create threads."""
        await self.bot.wait_until_ready()
        await self._open_game_threads()

    @tasks.loop(minutes=5)
    async def live_score_task(self) -> None:
        """Update live scores for active game threads."""
        await self.bot.wait_until_ready()
        await self._update_live_scores()

    # ---------------------------------------------------------------- background
    @tasks.loop(minutes=10)
    async def game_task(self) -> None:
        await self.bot.wait_until_ready()
        summary = await self.fetch_game_summary()
        if not summary:
            return
        event_id = summary.get("event_id")
        if not event_id or event_id in self.posted:
            return
        channel = self.bot.get_channel(getattr(cfg, "SPORTS_CHANNEL_ID", 0))
        if not isinstance(channel, discord.TextChannel):
            log.error("Sports channel not found")
            return
        try:
            msg = self.build_message(summary)
            message = await channel.send(msg)
            message_id = getattr(message, "id", None)
            stored_id = int(message_id) if message_id is not None else None
            self.posted.add(event_id)
            await self._mark_posted(event_id, stored_id)
        except Exception as exc:  # pragma: no cover - network
            log.exception("Failed to post game summary: %s", exc)


async def setup(bot: commands.Bot) -> None:  # pragma: no cover - entry point
    await bot.add_cog(MarinersGameCog(bot))
