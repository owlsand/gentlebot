"""Ensure Mariners game summaries respect the shared STATS_TIMEOUT value."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import gentlebot.cogs.mariners_game_cog as mariners_game_cog
from gentlebot.cogs.mariners_game_cog import MarinersGameCog
from gentlebot.cogs.sports_cog import STATS_TIMEOUT, TEAM_ID


@dataclass
class DummyResponse:
    """Minimal response object mimicking :class:`requests.Response`."""

    payload: dict[str, Any]

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class DummySession:
    """Context manager capturing timeout arguments passed to ``get``."""

    def __init__(self, responses: Iterable[DummyResponse], sink: list[Any]):
        self._responses = list(responses)
        self._timeouts = sink

    def mount(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def get(self, _url: str, *, timeout: Any | None = None) -> DummyResponse:
        self._timeouts.append(timeout)
        if not self._responses:
            raise AssertionError("No dummy response left for GET request")
        return self._responses.pop(0)

    def close(self) -> None:  # pragma: no cover - compatibility shim
        return None

    def __enter__(self) -> "DummySession":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def test_fetch_game_summary_uses_stats_timeout(monkeypatch) -> None:
    """All Mariners API requests should include ``timeout=STATS_TIMEOUT``."""

    timeouts: list[Any] = []

    def session_factory() -> DummySession:
        schedule_payload = {
            "dates": [
                {
                    "games": [
                        {
                            "gamePk": 555,
                            "status": {"detailedState": "Final"},
                            "teams": {
                                "home": {"team": {"id": TEAM_ID, "abbreviation": "SEA"}},
                                "away": {"team": {"id": 121, "abbreviation": "TEX"}},
                            },
                        }
                    ]
                }
            ]
        }

        feed_payload = {
            "gameData": {
                "teams": {
                    "home": {
                        "id": TEAM_ID,
                        "teamName": "Mariners",
                        "abbreviation": "SEA",
                    },
                    "away": {
                        "id": 121,
                        "teamName": "Rangers",
                        "abbreviation": "TEX",
                    },
                },
                "datetime": {"dateTime": "2024-05-01T03:10:00Z"},
            },
            "liveData": {
                "linescore": {
                    "teams": {"home": {"runs": 4}, "away": {"runs": 2}}
                },
                "plays": {"scoringPlays": [], "allPlays": []},
                "boxscore": {
                    "teams": {
                        "home": {"players": {}},
                        "away": {"players": {}},
                    }
                },
            },
        }

        standings_payload = {
            "records": [
                {
                    "teamRecords": [
                        {
                            "team": {"id": TEAM_ID, "abbreviation": "SEA"},
                            "wins": 10,
                            "losses": 5,
                            "streak": {"streakCode": "W1"},
                            "divisionRank": "1",
                            "gamesBack": "0.0",
                            "records": {
                                "splitRecords": [
                                    {
                                        "type": "lastTen",
                                        "wins": 7,
                                        "losses": 3,
                                    }
                                ]
                            },
                        },
                        {
                            "team": {"abbreviation": "HOU"},
                            "gamesBack": "1.0",
                        },
                    ]
                }
            ]
        }

        responses = [
            DummyResponse(schedule_payload),
            DummyResponse(feed_payload),
            DummyResponse(standings_payload),
        ]
        return DummySession(responses, timeouts)

    monkeypatch.setattr(mariners_game_cog.requests, "Session", session_factory)

    cog = MarinersGameCog(bot=None)
    summary = cog.fetch_game_summary()

    assert summary is not None
    assert timeouts == [STATS_TIMEOUT, STATS_TIMEOUT, STATS_TIMEOUT]
