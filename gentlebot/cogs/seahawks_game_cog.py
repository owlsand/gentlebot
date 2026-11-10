"""Seahawks game day updates in a single channel message, edited live.

One message per game is posted to the sports channel an hour before
kickoff with the projected score and win odds. The score task then edits
that same message whenever the score changes (and at the end of each
quarter), so the channel stays clean instead of spawning a thread per game
plus a message per quarter. Once the game starts the projection is dropped:
the live message leads with the current score, and at the final whistle it
is edited once more with the full post-game summary.

Score data comes from ESPN's site summary API. The per-quarter linescores
and totals live under ``header.competitions[0].competitors`` (the
``boxscore.teams[].linescores`` field the old thread cog read is null),
and passing yards are reported as ``netPassingYards``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import asyncio
import requests
from dateutil import parser
import pytz

import discord
from discord.ext import commands, tasks

from .. import bot_config as cfg
from ..capabilities import Category, CogCapabilities, ScheduledCapability

log = logging.getLogger(f"gentlebot.{__name__}")

PST = pytz.timezone("America/Los_Angeles")

SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
)

# A game is still "live" for tracking purposes this long after kickoff.
GAME_WINDOW = 6 * 60 * 60  # seconds


class SeahawksGameCog(commands.Cog):
    """Background task that posts one Seahawks game message and edits it live."""

    CAPABILITIES = CogCapabilities(
        scheduled=[
            ScheduledCapability(
                name="Seahawks game day message",
                schedule="Game days, 9:00 AM PT, then live edits",
                description=(
                    "Posts one Seahawks game day message with projections "
                    "and edits it after every score and at the final whistle"
                ),
                category=Category.SCHEDULED_LIVE,
            ),
        ]
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.opened: set[str] = set()
        # Game message tracking (all in-memory; see _ensure_tracking for
        # recovery after a restart mid-game)
        self.messages: Dict[str, discord.Message] = {}
        self.games: Dict[str, dict[str, Any]] = {}
        self.projections: Dict[str, dict[str, float]] = {}
        self.rendered: Dict[str, str] = {}
        self.final_posted: set[str] = set()  # Games with final summaries
        self.done: set[str] = set()  # Finished games, fully cleaned up
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
                    "opp_abbr": opp.get("team", {}).get("abbreviation", "OPP"),
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
        sum_url = f"{SUMMARY_URL}?event={game_id}"
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

    def fetch_game_state(self, game_id: str) -> Dict[str, Any]:
        """Return the live state of a game from the ESPN summary API.

        Quarter scores and totals come from the header competitors, whose
        ``linescores`` entries carry per-quarter points as ``displayValue``
        strings. Returns period number, game state (``pre``/``in``/``post``),
        clock, per-quarter lines, totals, and the latest scoring play.
        """
        resp = requests.get(f"{SUMMARY_URL}?event={game_id}", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        comp = (data.get("header", {}).get("competitions", [{}]) or [{}])[0]
        status = comp.get("status", {}) or {}
        state = (status.get("type", {}) or {}).get("state", "")
        try:
            period = int(status.get("period", 0) or 0)
        except (TypeError, ValueError):
            period = 0

        competitors = comp.get("competitors", []) or []
        sea_comp = next(
            (c for c in competitors
             if (c.get("team", {}) or {}).get("abbreviation") == "SEA"),
            None,
        )
        opp_comp = next(
            (c for c in competitors
             if (c.get("team", {}) or {}).get("abbreviation") != "SEA"),
            None,
        )

        def _lines(comp_: Optional[dict[str, Any]]) -> List[int]:
            if not comp_:
                return []
            out: List[int] = []
            for entry in comp_.get("linescores") or []:
                try:
                    out.append(int(entry.get("displayValue", 0)))
                except (TypeError, ValueError):
                    out.append(0)
            return out

        def _total(comp_: Optional[dict[str, Any]]) -> int:
            if not comp_:
                return 0
            try:
                return int(comp_.get("score", 0) or 0)
            except (TypeError, ValueError):
                return 0

        last_play: Optional[str] = None
        plays = data.get("scoringPlays") or []
        if plays:
            play = plays[-1]
            play_period = (play.get("period", {}) or {}).get("number")
            clock = (play.get("clock", {}) or {}).get("displayValue", "")
            text = (play.get("text") or "").strip()
            if play_period and text:
                last_play = f"Q{play_period} {clock} — {text}" if clock else f"Q{play_period} — {text}"

        return {
            "period": period,
            "state": state,
            "clock": status.get("displayClock", "") or "",
            "detail": (status.get("type", {}) or {}).get("shortDetail", "") or "",
            "sea_lines": _lines(sea_comp),
            "opp_lines": _lines(opp_comp),
            "sea_total": _total(sea_comp),
            "opp_total": _total(opp_comp),
            "last_play": last_play,
        }

    def fetch_game_summary(self, game_id: str) -> Dict[str, Any]:
        """Fetch post-game summary with key stats."""
        resp = requests.get(f"{SUMMARY_URL}?event={game_id}", timeout=10)
        resp.raise_for_status()
        data = resp.json()

        comp = (data.get("header", {}).get("competitions", [{}]) or [{}])[0]
        competitors = comp.get("competitors", []) or []
        sea_comp = next(
            (c for c in competitors
             if (c.get("team", {}) or {}).get("abbreviation") == "SEA"),
            None,
        )
        opp_comp = next(
            (c for c in competitors
             if (c.get("team", {}) or {}).get("abbreviation") != "SEA"),
            None,
        )
        if not sea_comp or not opp_comp:
            return {}

        # Final scores come from the header competitors, not from summing
        # linescores (boxscore linescores are null for NFL games).
        def _score(comp_: dict[str, Any]) -> int:
            try:
                return int(comp_.get("score", 0) or 0)
            except (TypeError, ValueError):
                return 0

        # Extract key stats from the boxscore teams
        box = data.get("boxscore", {}) or {}
        teams = box.get("teams", []) or []
        sea_team = next(
            (t for t in teams if (t.get("team", {}) or {}).get("abbreviation") == "SEA"),
            None,
        )
        opp_team = next(
            (t for t in teams if (t.get("team", {}) or {}).get("abbreviation") != "SEA"),
            None,
        )

        sea_stats = (sea_team or {}).get("statistics", []) or []
        opp_stats = (opp_team or {}).get("statistics", []) or []

        def _get_stat(stats: List[Dict], *names: str) -> str:
            for name in names:
                for stat in stats:
                    if stat.get("name") == name or stat.get("label") == name:
                        return stat.get("displayValue", "0")
            return "0"

        # Extract key stats (ESPN calls passing yards "netPassingYards")
        summary = {
            "sea_score": _score(sea_comp),
            "opp_score": _score(opp_comp),
            "opp_name": (opp_comp.get("team", {}) or {}).get("displayName", "Opponent"),
            "opp_abbr": (opp_comp.get("team", {}) or {}).get("abbreviation", "OPP"),
            "sea_passing_yards": _get_stat(sea_stats, "netPassingYards", "passingYards"),
            "sea_rushing_yards": _get_stat(sea_stats, "rushingYards"),
            "sea_total_yards": _get_stat(sea_stats, "totalYards"),
            "sea_turnovers": _get_stat(sea_stats, "turnovers"),
            "opp_passing_yards": _get_stat(opp_stats, "netPassingYards", "passingYards"),
            "opp_rushing_yards": _get_stat(opp_stats, "rushingYards"),
            "opp_total_yards": _get_stat(opp_stats, "totalYards"),
            "opp_turnovers": _get_stat(opp_stats, "turnovers"),
        }

        # Try to get key players from the game
        try:
            leaders = data.get("leaders", [])
            for leader in leaders:
                team = leader.get("team", {})
                if team.get("abbreviation") == "SEA":
                    for cat in leader.get("leaders", []):
                        if cat.get("name") in ("passingLeader", "passingYards"):
                            athlete = cat.get("leaders", [{}])[0].get("athlete", {})
                            summary["sea_qb"] = athlete.get("displayName", "")
                            summary["sea_qb_stats"] = cat.get("leaders", [{}])[0].get("displayValue", "")
                        elif cat.get("name") in ("rushingLeader", "rushingYards"):
                            athlete = cat.get("leaders", [{}])[0].get("athlete", {})
                            summary["sea_rb"] = athlete.get("displayName", "")
                            summary["sea_rb_stats"] = cat.get("leaders", [{}])[0].get("displayValue", "")
        except Exception:
            pass  # Leaders are optional

        return summary

    def _format_final_summary(self, summary: Dict[str, Any]) -> str:
        """Format the post-game summary message."""
        sea_score = summary.get("sea_score", 0)
        opp_score = summary.get("opp_score", 0)
        opp_name = summary.get("opp_name", "Opponent")

        # Determine win/loss
        if sea_score > opp_score:
            result = "🎉 **SEAHAWKS WIN!**"
        elif sea_score < opp_score:
            result = "😔 Seahawks lose"
        else:
            result = "🤝 **TIE GAME**"

        lines = [
            f"## {result}",
            f"**Final Score:** Seahawks {sea_score} - {opp_name} {opp_score}",
            "",
            "**Team Stats:**",
            f"• Total Yards: SEA {summary.get('sea_total_yards', '-')} | {summary.get('opp_abbr', 'OPP')} {summary.get('opp_total_yards', '-')}",
            f"• Passing: SEA {summary.get('sea_passing_yards', '-')} | {summary.get('opp_abbr', 'OPP')} {summary.get('opp_passing_yards', '-')}",
            f"• Rushing: SEA {summary.get('sea_rushing_yards', '-')} | {summary.get('opp_abbr', 'OPP')} {summary.get('opp_rushing_yards', '-')}",
            f"• Turnovers: SEA {summary.get('sea_turnovers', '-')} | {summary.get('opp_abbr', 'OPP')} {summary.get('opp_turnovers', '-')}",
        ]

        # Add key players if available
        if summary.get("sea_qb"):
            lines.append("")
            lines.append("**Key Performers:**")
            lines.append(f"• QB {summary['sea_qb']}: {summary.get('sea_qb_stats', '')}")
            if summary.get("sea_rb"):
                lines.append(f"• RB {summary['sea_rb']}: {summary.get('sea_rb_stats', '')}")

        return "\n".join(lines)

    # ---- helpers ----------------------------------------------------------------
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _period_label(period: int) -> str:
        if period <= 0:
            return ""
        if period <= 4:
            return f"Q{period}"
        if period == 5:
            return "OT"
        return f"OT{period - 4}"

    def _game_header(self, short: str, start_pst: datetime) -> str:
        time_str = start_pst.strftime("%a %-m/%-d, %-I:%M %p PT")
        return f"🏈 {short} — {time_str}"

    def _opening_message(
        self, proj: Optional[dict[str, float]], game: dict[str, Any]
    ) -> str:
        start_pst = game["start"].astimezone(PST)
        lines = [self._game_header(game["short"], start_pst)]
        if proj:
            lines.append(
                f"Projected score: Seahawks {proj['sea_score']:.0f} - "
                f"{game['opponent']} {proj['opp_score']:.0f}"
            )
            lines.append(
                f"Win odds: Seahawks {proj['sea_win']*100:.1f}%, "
                f"{game['opponent']} {proj['opp_win']*100:.1f}%"
            )
        lines.append("")
        lines.append("Live score updates will land here as the game goes.")
        return "\n".join(lines)

    def _render_body(
        self,
        game: dict[str, Any],
        proj: Optional[dict[str, float]],
        state: Dict[str, Any],
        summary: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Render the full message body for the game's current state.

        While the game is live the current score is the headline, right
        under the matchup line; quarter lines and the projection sit below
        it as supporting detail.
        """
        start_pst = game["start"].astimezone(PST)
        opp_abbr = game.get("opp_abbr", "OPP")
        opp_short = game["opponent"].split()[-1]
        game_state = state.get("state", "")
        sea_lines = state.get("sea_lines", [])
        opp_lines = state.get("opp_lines", [])
        lines = [self._game_header(game["short"], start_pst)]

        def _projection_lines() -> List[str]:
            if not proj:
                return []
            return [
                f"Projected score: Seahawks {proj['sea_score']:.0f} - "
                f"{game['opponent']} {proj['opp_score']:.0f}",
                f"Win odds: Seahawks {proj['sea_win']*100:.1f}%, "
                f"{game['opponent']} {proj['opp_win']*100:.1f}%",
            ]

        def _quarter_lines() -> List[str]:
            out = []
            for idx in range(min(len(sea_lines), len(opp_lines))):
                label = self._period_label(idx + 1)
                out.append(f"{label}: SEA {sea_lines[idx]} - {opp_abbr} {opp_lines[idx]}")
            return out

        if game_state == "post":
            lines.append("")
            lines.extend(_quarter_lines())
            if summary:
                lines.append("")
                lines.append(self._format_final_summary(summary))
            else:
                lines.append(
                    f"✅ Final — Seahawks {state.get('sea_total', 0)} - "
                    f"{game['opponent']} {state.get('opp_total', 0)}"
                )
            return "\n".join(lines)

        if game_state == "in":
            sea_total = state.get("sea_total", 0)
            opp_total = state.get("opp_total", 0)
            lines.append(f"## Seahawks {sea_total} — {opp_short} {opp_total}")
            quarter = _quarter_lines()
            if quarter:
                lines.append("")
                lines.extend(quarter)
            if state.get("last_play"):
                lines.append("")
                lines.append(f"Last score: {state['last_play']}")
            return "\n".join(lines)

        lines.extend(_projection_lines())
        lines.append("")
        lines.append("Live score updates will land here as the game goes.")
        return "\n".join(lines)

    def _sports_channel(self) -> Optional[discord.TextChannel]:
        channel = self.bot.get_channel(cfg.SPORTS_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            log.error("Sports channel not found")
            return None
        return channel

    async def _open_game_messages(self) -> None:
        now = self._now()
        try:
            games = self.fetch_schedule()
        except Exception:  # pragma: no cover - network
            log.exception("Failed to fetch Seahawks schedule")
            return
        for g in games:
            if g["id"] in self.opened:
                continue
            # The preview lands an hour before kickoff: post once the game
            # is within an hour and hasn't started yet.
            open_time = g["start"] - timedelta(hours=1)
            if not (open_time <= now < g["start"]):
                continue
            channel = self._sports_channel()
            if channel is None:
                self.opened.add(g["id"])
                continue
            try:
                proj = self.fetch_projection(g["id"])
            except Exception:  # pragma: no cover - network
                log.exception("Failed to fetch projection for %s", g["short"])
                proj = None
            body = self._opening_message(proj, g)
            try:
                message = await channel.send(body)
            except Exception:  # pragma: no cover - network
                log.exception("Failed to post game message for %s", g["short"])
                continue
            self.opened.add(g["id"])
            self.messages[g["id"]] = message
            self.games[g["id"]] = g
            if proj is not None:
                self.projections[g["id"]] = proj
            self.rendered[g["id"]] = body

    async def _adopt_message(
        self, channel: discord.TextChannel, game: dict[str, Any]
    ) -> Optional[discord.Message]:
        """Find this game's message in recent channel history (restart recovery)."""
        header = self._game_header(
            game["short"], game["start"].astimezone(PST)
        )
        try:
            async for msg in channel.history(limit=100):
                if getattr(msg.author, "bot", False) and msg.content.startswith(header):
                    return msg
        except Exception:  # pragma: no cover - network
            log.exception("Failed to scan channel history for %s", game["short"])
        return None

    async def _ensure_tracking(self) -> None:
        """Recover tracking for a game that started while the bot was down.

        Only runs when nothing is currently tracked (a restart clears the
        in-memory state). For a game that kicked off within the window,
        adopt its message from channel history, or post a fresh one if the
        bot was down when the preview should have gone out. No projection
        is needed here: once a game is live or final the message carries
        the score, not the preview.
        """
        if self.messages:
            return
        now = self._now()
        try:
            games = self.fetch_schedule()
        except Exception:  # pragma: no cover - network
            log.exception("Failed to fetch Seahawks schedule for recovery")
            return
        channel = self._sports_channel()
        if channel is None:
            return
        for g in games:
            gid = g["id"]
            if gid in self.done or gid in self.messages:
                continue
            start = g["start"]
            if start > now:
                continue
            if (now - start).total_seconds() > GAME_WINDOW:
                continue
            try:
                state = self.fetch_game_state(gid)
            except Exception:  # pragma: no cover - network
                log.exception("Failed to fetch state for %s", g["short"])
                continue
            if state.get("state") not in ("in", "post"):
                continue
            message = await self._adopt_message(channel, g)
            if message is not None:
                self.messages[gid] = message
                self.games[gid] = g
                self.rendered[gid] = message.content
                self.opened.add(gid)
                log.info("Recovered Seahawks game message for %s", g["short"])
            else:
                body = self._opening_message(None, g)
                try:
                    message = await channel.send(body)
                except Exception:  # pragma: no cover - network
                    log.exception("Failed to post recovery message for %s", g["short"])
                    continue
                self.opened.add(gid)
                self.messages[gid] = message
                self.games[gid] = g
                self.rendered[gid] = body
                log.info("Posted late Seahawks game message for %s", g["short"])

    # ---- background loop -------------------------------------------------------
    @tasks.loop(minutes=5)
    async def game_task(self) -> None:
        await self.bot.wait_until_ready()
        await self._open_game_messages()

    async def _update_scores(self) -> None:
        """Edit each tracked game message when its score or status changes."""
        await self._ensure_tracking()
        for gid, message in list(self.messages.items()):
            game = self.games.get(gid)
            if game is None:
                continue
            try:
                state = self.fetch_game_state(gid)
            except Exception:  # pragma: no cover - network
                log.exception("Failed to fetch state for %s", gid)
                continue

            summary: Optional[Dict[str, Any]] = None
            if state.get("state") == "post" and gid not in self.final_posted:
                try:
                    summary = self.fetch_game_summary(gid)
                except Exception:  # pragma: no cover - network
                    log.exception("Failed to fetch final summary for %s", gid)
                    summary = None
                if summary:
                    self.final_posted.add(gid)

            body = self._render_body(
                game, self.projections.get(gid), state, summary
            )
            if body == self.rendered.get(gid):
                continue
            try:
                await message.edit(content=body)
                self.rendered[gid] = body
            except discord.NotFound:
                # Someone deleted the message; re-post it once.
                channel = self._sports_channel()
                if channel is None:
                    self.messages.pop(gid, None)
                    continue
                try:
                    new_message = await channel.send(body)
                except Exception:  # pragma: no cover - network
                    log.exception("Failed to re-post game message for %s", gid)
                    self.messages.pop(gid, None)
                    continue
                self.messages[gid] = new_message
                self.rendered[gid] = body
            except Exception:  # pragma: no cover - network
                log.exception("Failed to edit game message for %s", gid)

            if state.get("state") == "post" and gid in self.final_posted:
                # Final summary is in the message; stop polling this game.
                self.messages.pop(gid, None)
                self.games.pop(gid, None)
                self.projections.pop(gid, None)
                self.rendered.pop(gid, None)
                self.done.add(gid)

    @tasks.loop(minutes=2)
    async def score_task(self) -> None:
        await self.bot.wait_until_ready()
        await self._update_scores()


async def setup(bot: commands.Bot):
    await bot.add_cog(SeahawksGameCog(bot))
