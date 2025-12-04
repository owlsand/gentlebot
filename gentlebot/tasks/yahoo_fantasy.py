"""Utilities for Yahoo Fantasy Football weekly recaps."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Sequence

import aiohttp

log = logging.getLogger(f"gentlebot.{__name__}")

TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"


@dataclass
class TeamResult:
    """Score and metadata for a single fantasy team."""

    name: str
    points: Decimal


@dataclass
class MatchupResult:
    """Represents a head-to-head matchup for the week."""

    teams: tuple[TeamResult, TeamResult]
    is_tied: bool = False
    status: str | None = None
    week: int | None = None

    @property
    def margin(self) -> Decimal:
        """Return the absolute scoring differential between the teams."""

        a, b = self.teams
        return (a.points - b.points).copy_abs()


@dataclass
class WeeklyRecap:
    """Container for all matchup outcomes in a week."""

    league_name: str
    week: int
    matchups: list[MatchupResult]

    def is_final(self) -> bool:
        """Return True if every matchup reports a "postevent" status."""

        statuses = []
        for matchup in self.matchups:
            if not matchup.status:
                continue
            normalized = (
                matchup.status.lower()
                .replace(" ", "")
                .replace("-", "")
                .replace("_", "")
            )
            if normalized:
                statuses.append(normalized)
        if not statuses:
            return True
        final_statuses = {
            "postevent",
            "postgame",
            "final",
            "finalized",
            "complete",
            "completed",
        }
        return all(status in final_statuses for status in statuses)


@dataclass
class LeagueContext:
    """Metadata describing the league and season state."""

    name: str | None = None
    current_week: int | None = None
    start_week: int | None = None


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("-"):
            text = text[1:]
        if text.isdigit():
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        for key in ("full", "name", "nickname", "display"):
            if key in value:
                text = _stringify(value[key])
                if text:
                    return text
        for sub in value.values():
            text = _stringify(sub)
            if text:
                return text
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            text = _stringify(item)
            if text:
                return text
    return ""


def _extract_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return Decimal(text)
        except InvalidOperation:
            return None
    if isinstance(value, dict):
        for key in ("total", "value", "points", "score"):
            if key in value:
                dec = _extract_decimal(value[key])
                if dec is not None:
                    return dec
        for sub in value.values():
            dec = _extract_decimal(sub)
            if dec is not None:
                return dec
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            dec = _extract_decimal(item)
            if dec is not None:
                return dec
    return None


def _extract_team_entries(node: Any) -> list[Any]:
    results: list[Any] = []
    if isinstance(node, dict):
        if "team" in node:
            results.append(node["team"])
        else:
            for value in node.values():
                results.extend(_extract_team_entries(value))
    elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
        for item in node:
            results.extend(_extract_team_entries(item))
    return results


def _parse_team(node: Any) -> TeamResult:
    name: str | None = None
    points: Decimal | None = None

    def _walk(value: Any) -> None:
        nonlocal name, points
        if isinstance(value, dict):
            for key, sub in value.items():
                if key == "name" and name is None:
                    text = _stringify(sub)
                    if text:
                        name = text
                elif key == "team_points" and points is None:
                    points = _extract_decimal(sub)
                else:
                    _walk(sub)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                _walk(item)

    _walk(node)

    if name is None:
        raise ValueError("Team name missing from Yahoo response")
    if points is None:
        raise ValueError(f"Team points missing for {name}")
    return TeamResult(name=name, points=points)


def _collect_matchup_nodes(node: Any) -> list[Any]:
    matchups: list[Any] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "matchups":
                matchups.extend(_collect_matchup_nodes(value))
            elif key == "matchup":
                matchups.extend(_ensure_list(value))
            else:
                matchups.extend(_collect_matchup_nodes(value))
    elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
        for item in node:
            matchups.extend(_collect_matchup_nodes(item))
    return matchups


def _parse_matchup(node: Any) -> MatchupResult:
    teams: list[TeamResult] = []
    is_tied = False
    status: str | None = None
    week: int | None = None

    def _walk(value: Any) -> None:
        nonlocal is_tied, status, week
        if isinstance(value, dict):
            for key, sub in value.items():
                if key == "teams":
                    team_entries = _extract_team_entries(sub)
                    teams.extend(_parse_team(entry) for entry in team_entries)
                elif key == "is_tied":
                    is_tied = _coerce_bool(sub)
                elif key == "status" and isinstance(sub, str):
                    status = sub
                elif key == "week" and week is None:
                    parsed = _safe_int(sub)
                    if parsed is not None:
                        week = parsed
                else:
                    _walk(sub)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                _walk(item)

    _walk(node)

    if len(teams) < 2:
        raise ValueError("Expected two teams in Yahoo matchup response")
    ordered = teams[:2]
    return MatchupResult(teams=(ordered[0], ordered[1]), is_tied=is_tied, status=status, week=week)


def _find_scoreboard_node(league_node: Any) -> Any:
    if isinstance(league_node, dict):
        if "scoreboard" in league_node:
            return league_node["scoreboard"]
        for value in league_node.values():
            result = _find_scoreboard_node(value)
            if result is not None:
                return result
    elif isinstance(league_node, Sequence) and not isinstance(league_node, (str, bytes, bytearray)):
        for item in league_node:
            result = _find_scoreboard_node(item)
            if result is not None:
                return result
    return None


def _extract_scoreboard_week(scoreboard_node: Any) -> int | None:
    if isinstance(scoreboard_node, dict):
        if "week" in scoreboard_node:
            parsed = _safe_int(scoreboard_node["week"])
            if parsed is not None:
                return parsed
        for value in scoreboard_node.values():
            parsed = _extract_scoreboard_week(value)
            if parsed is not None:
                return parsed
    elif isinstance(scoreboard_node, Sequence) and not isinstance(scoreboard_node, (str, bytes, bytearray)):
        for item in scoreboard_node:
            parsed = _extract_scoreboard_week(item)
            if parsed is not None:
                return parsed
    return None


def extract_league_context(payload: dict[str, Any]) -> LeagueContext:
    """Pull high level league metadata from the Yahoo response."""

    context = LeagueContext()
    league = payload.get("fantasy_content", {}).get("league")

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if ("league_id" in node or "league_key" in node) and node.get("name") and context.name is None:
                context.name = _stringify(node.get("name"))
            if "current_week" in node and context.current_week is None:
                context.current_week = _safe_int(node["current_week"])
            if "start_week" in node and context.start_week is None:
                context.start_week = _safe_int(node["start_week"])
            for value in node.values():
                _walk(value)
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
            for item in node:
                _walk(item)

    if league is not None:
        _walk(league)
    return context


def determine_target_week(context: LeagueContext) -> int | None:
    """Return the most recent completed scoring week for recap."""

    if context.current_week is None and context.start_week is None:
        return None
    start = context.start_week or 1
    current = context.current_week or start
    if current <= start:
        return start
    return max(start, current - 1)


def parse_weekly_scoreboard(
    payload: dict[str, Any],
    *,
    fallback_name: str | None = None,
    fallback_week: int | None = None,
) -> WeeklyRecap:
    """Convert the Yahoo scoreboard payload into a WeeklyRecap."""

    league_node = payload.get("fantasy_content", {}).get("league")
    if league_node is None:
        raise ValueError("Yahoo response missing league information")

    scoreboard = _find_scoreboard_node(league_node)
    if scoreboard is None:
        raise ValueError("Yahoo response missing scoreboard data")

    context = extract_league_context(payload)
    league_name = context.name or fallback_name or "Fantasy League"

    matchups_raw = _collect_matchup_nodes(scoreboard)
    if not matchups_raw:
        raise ValueError("Yahoo scoreboard did not contain matchups")

    matchups: list[MatchupResult] = []
    for entry in matchups_raw:
        try:
            matchups.append(_parse_matchup(entry))
        except ValueError as exc:
            log.warning("Skipping invalid matchup entry: %s", exc)

    if not matchups:
        raise ValueError("No valid matchups found in Yahoo response")

    week = _extract_scoreboard_week(scoreboard)
    if week is None:
        for matchup in matchups:
            if matchup.week is not None:
                week = matchup.week
                break
    if week is None:
        week = fallback_week or context.current_week
    if week is None:
        raise ValueError("Unable to determine scoring week from Yahoo response")

    return WeeklyRecap(league_name=league_name, week=week, matchups=matchups)


def _format_decimal(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return format(quantized, ".1f")


def format_weekly_recap(recap: WeeklyRecap) -> str:
    """Render the weekly recap Discord message."""

    def _classify_margin(margin: Decimal, tied: bool) -> tuple[str, str]:
        if tied or margin == Decimal("0"):
            return "🤝", "(tie)"
        if margin >= Decimal("40"):
            return "🔥", "(blowout win)"
        if margin >= Decimal("25"):
            return "💪", "(dominant win)"
        if margin >= Decimal("10"):
            return "✅", ""
        if margin >= Decimal("5"):
            return "😤", "(close one)"
        return "😬", "(nail-biter)"

    high_team: TeamResult | None = None
    low_team: TeamResult | None = None
    matchup_lines: list[tuple[Decimal, str]] = []

    for matchup in recap.matchups:
        team_a, team_b = matchup.teams
        tied = matchup.is_tied or team_a.points == team_b.points
        if tied:
            primary, secondary = team_a, team_b
            raw_margin = Decimal("0")
        else:
            primary, secondary = (
                (team_a, team_b) if team_a.points >= team_b.points else (team_b, team_a)
            )
            raw_margin = (primary.points - secondary.points).copy_abs()

        margin = raw_margin.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        emoji, suffix = _classify_margin(margin, tied)
        suffix_text = f" {suffix}" if suffix else ""
        line = (
            f"{emoji} {primary.name} {_format_decimal(primary.points)} – "
            f"{_format_decimal(secondary.points)} {secondary.name}{suffix_text}"
        )
        matchup_lines.append((max(team_a.points, team_b.points), line))

        for team in (team_a, team_b):
            if high_team is None or team.points > high_team.points:
                high_team = team
            if low_team is None or team.points < low_team.points:
                low_team = team

    if not matchup_lines or high_team is None or low_team is None:
        raise ValueError("Weekly recap requires finalized matchups to format output")

    matchup_lines.sort(key=lambda item: item[0], reverse=True)
    matchup_text = "\n".join(line for _, line in matchup_lines)

    summary_lines = [
        f"👑 **Best**: {high_team.name} ({_format_decimal(high_team.points)})",
        f"💀 **Worst**: {low_team.name} ({_format_decimal(low_team.points)})",
    ]

    sections = [f"🦄 🏈 **Gentlefolk Week {recap.week} Recap**", matchup_text, "\n".join(summary_lines)]
    return "\n\n".join(sections)


async def fetch_access_token(
    session: aiohttp.ClientSession,
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> str:
    """Exchange a refresh token for a Yahoo OAuth access token."""

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "redirect_uri": "oob",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with session.post(TOKEN_URL, data=payload, headers=headers) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(
                f"Yahoo token request failed with status {resp.status}: {body[:200]}"
            )
        data = await resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Yahoo token response missing access_token")
    return token


async def fetch_scoreboard(
    session: aiohttp.ClientSession,
    *,
    access_token: str,
    league_key: str,
    week: int | None = None,
) -> dict[str, Any]:
    """Fetch the scoreboard JSON from Yahoo for a given week."""

    path = f"league/{league_key}/scoreboard"
    if week is not None:
        path += f";week={week}"
    params = {"format": "json"}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    async with session.get(f"{API_BASE}/{path}", params=params, headers=headers) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(
                f"Yahoo scoreboard request failed with status {resp.status}: {body[:200]}"
            )
        return await resp.json()
