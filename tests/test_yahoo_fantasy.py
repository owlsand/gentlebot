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
        "🦄 🏈 **Gentlefolk Week 2 Recap**\n"
        "\n"
        "💪 Spencer’s Singularity AI Ed. 135.5 – 105.6 ChristopherZ’s Cool Team (dominant win)\n"
        "💪 Andrew’s 12th Man Blitz 129.7 – 100.8 Chicago Slice (dominant win)\n"
        "✅ Habitual Hail Marys 115.3 – 98.9 Mighty Muffins\n"
        "✅ Amber’s Agreeable Team 107.5 – 91.4 Kyle’s Average Team\n"
        "✅ Macaroni Penguins 94.4 – 75.9 The Wingin’ Itter’s\n"
        "💪 Don Stop Believing 91.4 – 66.4 Dooga’s Nukas (dominant win)\n"
        "\n"
        "👑 **Best**: Spencer’s Singularity AI Ed. (135.5)\n"
        "💀 **Worst**: Dooga’s Nukas (66.4)"
    )
    assert message == expected


def test_determine_target_week_uses_previous_week() -> None:
    context = LeagueContext(name="Gentlefolk2.0", current_week=3, start_week=1)
    assert determine_target_week(context) == 2
