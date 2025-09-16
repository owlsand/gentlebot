"""Automatically post Mariners game summaries after each final result."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

import asyncio
import asyncpg
import pytz
import requests
from dateutil import parser
from requests.adapters import HTTPAdapter, Retry

import discord
from discord.ext import commands, tasks

from .sports_cog import PST_TZ, STATS_TIMEOUT
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


class MarinersGameCog(commands.Cog):
    """Background task posting a summary after each Mariners game."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.posted: set[str] = set()
        self.pool: asyncpg.Pool | None = None
        self.tracking_since: datetime = datetime.now(tz=pytz.utc)

    async def cog_load(self) -> None:  # pragma: no cover - startup
        pool: asyncpg.Pool | None = None
        try:
            self.pool = await get_pool()
            await self._ensure_table()
            await self._ensure_tracking_state()
            await self._sync_schedule()
            await self._load_posted()
        except Exception as exc:  # pragma: no cover - database init
            log.warning(
                "MarinersGameCog disabled database persistence: %s", exc
            )
        else:
            try:
                self.pool = pool
                await self._ensure_table()
                await self._load_posted()
            except Exception as exc:  # pragma: no cover - defensive
                self.pool = None
                log.warning(
                    "MarinersGameCog disabled database persistence: %s", exc
                )
                try:
                    await pool.close()
                except Exception:  # pragma: no cover - defensive
                    log.debug("Failed closing Mariners DB pool after setup error", exc_info=True)
        self.game_task.start()

    async def cog_unload(self) -> None:  # pragma: no cover - cleanup
        self.game_task.cancel()

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

    async def fetch_game_summary(self) -> Optional[Dict[str, Any]]:
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
