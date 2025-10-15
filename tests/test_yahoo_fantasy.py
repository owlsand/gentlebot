"""Tests for Yahoo Fantasy weekly recap formatting."""
from __future__ import annotations

from gentlebot.tasks.yahoo_fantasy import (
    LeagueContext,
    determine_target_week,
    format_weekly_recap,
    parse_weekly_scoreboard,
)


def _team_entry(name: str, points: str, variant: str) -> dict:
    if variant == "list":
        return {"team": [{"name": name}, {"team_points": {"total": points}}]}
    if variant == "dict":
        return {
            "team": {
                "0": {"name": name},
                "1": {"team_points": {"total": points}},
            }
        }
    # mixed form nests totals in a list
    return {
        "team": [
            {"name": name},
            {"team_points": [{"total": points}, {"week": "2"}]},
        ]
    }


def _build_payload() -> dict:
    matchup_specs = [
        (
            "Don Stop Believing",
            "91.42",
            "Dooga’s Nukas",
            "66.44",
            "list",
            "dict",
        ),
        (
            "Habitual Hail Marys",
            "115.28",
            "Mighty Muffins",
            "98.90",
            "dict",
            "mixed",
        ),
        (
            "Amber’s Agreeable Team",
            "107.54",
            "Kyle’s Average Team",
            "91.40",
            "mixed",
            "list",
        ),
        (
            "Spencer’s Singularity AI Ed.",
            "135.50",
            "ChristopherZ’s Cool Team",
            "105.60",
            "list",
            "dict",
        ),
        (
            "Andrew’s 12th Man Blitz",
            "129.74",
            "Chicago Slice",
            "100.84",
            "dict",
            "mixed",
        ),
        (
            "Macaroni Penguins",
            "94.42",
            "The Wingin’ Itter’s",
            "75.88",
            "mixed",
            "list",
        ),
    ]

    matchups: dict[str, dict] = {}
    for idx, (home, home_pts, away, away_pts, var_home, var_away) in enumerate(matchup_specs):
        matchups[str(idx)] = {
            "matchup": [
                {"matchup_id": str(idx + 1)},
                {"week": "2"},
                {"status": "postevent"},
                {"is_tied": "0"},
                {
                    "teams": {
                        "0": _team_entry(home, home_pts, var_home),
                        "1": _team_entry(away, away_pts, var_away),
                    }
                },
            ]
        }

    payload = {
        "fantasy_content": {
            "league": {
                "0": {
                    "league_key": "423.l.12345",
                    "league_id": "12345",
                    "name": "Gentlefolk2.0",
                    "current_week": "3",
                    "start_week": "1",
                },
                "1": {
                    "scoreboard": {
                        "0": {"week": "2"},
                        "1": {"matchups": matchups},
                    }
                },
                "current_week": "3",
            }
        }
    }
    return payload


def test_format_weekly_recap_matches_expected() -> None:
    payload = _build_payload()
    recap = parse_weekly_scoreboard(payload)
    message = format_weekly_recap(recap)
    expected = (
        "🏈 *Gentlefolk2.0 Week 2 Recap* :unicorn:\n"
        "Matchups\n"
        "• Don Stop Believing 91.42 def. Dooga’s Nukas 66.44  (Δ 24.98)\n"
        "• Habitual Hail Marys 115.28 def. Mighty Muffins 98.90  (Δ 16.38)\n"
        "• Amber’s Agreeable Team 107.54 def. Kyle’s Average Team 91.40  (Δ 16.14)\n"
        "• Spencer’s Singularity AI Ed. 135.50 def. ChristopherZ’s Cool Team 105.60  (Δ 29.90)\n"
        "• Andrew’s 12th Man Blitz 129.74 def. Chicago Slice 100.84  (Δ 28.90)\n"
        "• Macaroni Penguins 94.42 def. The Wingin’ Itter’s 75.88  (Δ 18.54)\n\n"
        "High Score: Spencer’s Singularity AI Ed. — 135.50\n"
        "Closest Game: Amber’s Agreeable Team vs Kyle’s Average Team — Δ 16.14 pts\n"
        "Low Score: Dooga’s Nukas — 66.44"
    )
    assert message == expected


def test_determine_target_week_uses_previous_week() -> None:
    context = LeagueContext(name="Gentlefolk2.0", current_week=3, start_week=1)
    assert determine_target_week(context) == 2
