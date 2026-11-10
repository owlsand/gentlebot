import asyncio
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands
from gentlebot.cogs.seahawks_game_cog import SeahawksGameCog, PST


class FakeMessage:
    def __init__(self, content):
        self.content = content
        self.id = 123456
        self.author = SimpleNamespace(bot=True)
        self.edits = []

    async def edit(self, content=None, **kwargs):
        self.edits.append(content)
        self.content = content


class FakeChannel:
    def __init__(self, history_msgs=None):
        self.sent = []
        self._history = history_msgs or []

    async def send(self, content):
        msg = FakeMessage(content)
        self.sent.append(msg)
        return msg

    async def history(self, limit=100):
        for m in self._history:
            yield m


def _make_cog(monkeypatch):
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)
    monkeypatch.setattr(bot, "loop", SimpleNamespace(create_task=lambda c: None))
    # Stop the background loops from starting: __init__ starts them, and
    # sync tests have no running event loop for tasks.loop.start().
    monkeypatch.setattr(SeahawksGameCog, "game_task", SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(SeahawksGameCog, "score_task", SimpleNamespace(start=lambda: None))
    return SeahawksGameCog(bot)


def _game(start):
    return {
        "id": "g1",
        "opponent": "Rams",
        "opp_abbr": "LAR",
        "short": "LAR @ SEA",
        "start": start,
    }


def _state(period, state, sea_lines, opp_lines, sea_total, opp_total,
           clock="", last_play=None):
    return {
        "period": period,
        "state": state,
        "clock": clock,
        "detail": "",
        "sea_lines": sea_lines,
        "opp_lines": opp_lines,
        "sea_total": sea_total,
        "opp_total": opp_total,
        "last_play": last_play,
    }


def test_posts_single_message_with_projection(monkeypatch):
    async def run_test():
        cog = _make_cog(monkeypatch)
        start = PST.localize(datetime(2024, 1, 1, 17, 30)).astimezone(timezone.utc)
        monkeypatch.setattr(cog, "fetch_schedule", lambda: [_game(start)])
        projection = {"sea_score": 24, "opp_score": 21, "sea_win": 0.55, "opp_win": 0.45}
        monkeypatch.setattr(cog, "fetch_projection", lambda gid: projection)

        channel = FakeChannel()
        monkeypatch.setattr(cog, "_sports_channel", lambda: channel)
        # The channel must not offer thread creation: this is a regression
        # guard for the old per-game thread behaviour.
        assert not hasattr(channel, "create_thread")

        # The preview posts in the hour before kickoff, not at 9 AM.
        now = PST.localize(datetime(2024, 1, 1, 16, 35)).astimezone(timezone.utc)
        monkeypatch.setattr(cog, "_now", lambda: now)

        await cog._open_game_messages()
        assert len(channel.sent) == 1
        body = channel.sent[0].content
        assert body.startswith("🏈 LAR @ SEA — Mon 1/1, 5:30 PM PT")
        assert "Projected score: Seahawks 24 - Rams 21" in body
        assert "Win odds: Seahawks 55.0%, Rams 45.0%" in body
        assert "Live score updates will land here as the game goes." in body
        assert cog.messages["g1"] is channel.sent[0]

    asyncio.run(run_test())


def test_preview_waits_until_one_hour_before_kickoff(monkeypatch):
    async def run_test():
        cog = _make_cog(monkeypatch)
        start = PST.localize(datetime(2024, 1, 1, 17, 30)).astimezone(timezone.utc)
        monkeypatch.setattr(cog, "fetch_schedule", lambda: [_game(start)])
        projection = {"sea_score": 24, "opp_score": 21, "sea_win": 0.55, "opp_win": 0.45}
        monkeypatch.setattr(cog, "fetch_projection", lambda gid: projection)

        channel = FakeChannel()
        monkeypatch.setattr(cog, "_sports_channel", lambda: channel)
        clock = {"now": PST.localize(datetime(2024, 1, 1, 9, 5)).astimezone(timezone.utc)}
        monkeypatch.setattr(cog, "_now", lambda: clock["now"])

        await cog._open_game_messages()
        assert channel.sent == []  # 9 AM is too early; preview waits

        clock["now"] = PST.localize(datetime(2024, 1, 1, 16, 29)).astimezone(timezone.utc)
        await cog._open_game_messages()
        assert channel.sent == []  # 61 minutes out is still too early

        clock["now"] = PST.localize(datetime(2024, 1, 1, 16, 35)).astimezone(timezone.utc)
        await cog._open_game_messages()
        assert len(channel.sent) == 1  # inside the hour: posted

    asyncio.run(run_test())


def test_fetch_schedule_skips_bye_week(monkeypatch):
    data = {
        "events": [
            {
                "id": "g1",
                "shortName": "SEA @ LAR",
                "competitions": [
                    {
                        "date": "2024-01-01T17:30Z",
                        "competitors": [
                            {"team": {"abbreviation": "SEA"}},
                            {
                                "team": {
                                    "abbreviation": "LAR",
                                    "displayName": "Rams",
                                }
                            },
                        ],
                    }
                ],
            },
            {
                "id": "bye1",
                "shortName": "BYE",
                "competitions": [
                    {
                        "date": "2024-10-01T17:30Z",
                        "competitors": [
                            {
                                "team": {
                                    "abbreviation": "SEA",
                                    "displayName": "Seahawks",
                                }
                            }
                        ],
                    }
                ],
            },
        ]
    }

    class FakeResp:
        def json(self):
            return data

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "gentlebot.cogs.seahawks_game_cog.requests.get", lambda url, timeout=10: FakeResp()
    )

    cog = _make_cog(monkeypatch)
    games = cog.fetch_schedule()
    assert len(games) == 1
    assert games[0]["opponent"] == "Rams"
    assert games[0]["opp_abbr"] == "LAR"
    assert games[0]["short"] == "SEA @ LAR"


def test_fetch_projection(monkeypatch):
    predictor = {
        "homeTeam": {
            "team": {
                "$ref": "http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2024/teams/26?lang=en&region=us"
            },
            "statistics": [
                {"name": "gameProjection", "value": 24.0},
                {"name": "gameProjectionProbability", "value": 60.0},
            ],
        },
        "awayTeam": {
            "team": {
                "$ref": "http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2024/teams/10?lang=en&region=us"
            },
            "statistics": [
                {"name": "gameProjection", "value": 16.0},
                {"name": "teamOddsWinPercentage", "value": 40.0},
            ],
        },
    }

    summary = {"pickcenter": [{"overUnder": 40.0, "spread": -4.0}]}

    class FakeResp:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

        def raise_for_status(self):
            return None

    def fake_get(url, timeout=10):
        if "predictor" in url:
            return FakeResp(predictor)
        return FakeResp(summary)

    monkeypatch.setattr(
        "gentlebot.cogs.seahawks_game_cog.requests.get", fake_get
    )

    cog = _make_cog(monkeypatch)
    proj = cog.fetch_projection("gid")
    assert proj == {
        "sea_score": 22.0,
        "opp_score": 18.0,
        "sea_win": 0.6,
        "opp_win": 0.4,
    }


# ESPN summary payload shaped like the real ARI @ SEA 2026-11-08 response:
# quarter scores live in header.competitors[].linescores (displayValue
# strings), boxscore.teams[].linescores is null, and passing yards are
# reported as netPassingYards.
_SUMMARY_PAYLOAD = {
    "header": {
        "competitions": [
            {
                "status": {
                    "period": 4,
                    "displayClock": "0:00",
                    "type": {"state": "post", "shortDetail": "Final"},
                },
                "competitors": [
                    {
                        "homeAway": "home",
                        "team": {"abbreviation": "SEA", "displayName": "Seattle Seahawks"},
                        "score": "17",
                        "linescores": [
                            {"displayValue": "0"},
                            {"displayValue": "14"},
                            {"displayValue": "3"},
                            {"displayValue": "0"},
                        ],
                    },
                    {
                        "homeAway": "away",
                        "team": {"abbreviation": "ARI", "displayName": "Arizona Cardinals"},
                        "score": "3",
                        "linescores": [
                            {"displayValue": "3"},
                            {"displayValue": "0"},
                            {"displayValue": "0"},
                            {"displayValue": "0"},
                        ],
                    },
                ],
            }
        ]
    },
    "boxscore": {
        "teams": [
            {
                "team": {"abbreviation": "SEA"},
                "linescores": None,
                "statistics": [
                    {"name": "totalYards", "displayValue": "295"},
                    {"name": "netPassingYards", "displayValue": "175"},
                    {"name": "rushingYards", "displayValue": "120"},
                    {"name": "turnovers", "displayValue": "0"},
                ],
            },
            {
                "team": {"abbreviation": "ARI"},
                "linescores": None,
                "statistics": [
                    {"name": "totalYards", "displayValue": "198"},
                    {"name": "netPassingYards", "displayValue": "148"},
                    {"name": "rushingYards", "displayValue": "50"},
                    {"name": "turnovers", "displayValue": "0"},
                ],
            },
        ]
    },
    "scoringPlays": [
        {
            "text": "Chad Ryland 28 Yd Field Goal ",
            "period": {"number": 1},
            "clock": {"displayValue": "9:23"},
        },
        {
            "text": "AJ Barner 7 Yd pass from Drew Lock",
            "period": {"number": 2},
            "clock": {"displayValue": "0:15"},
        },
    ],
    "leaders": [
        {
            "team": {"abbreviation": "SEA"},
            "leaders": [
                {
                    "name": "passingYards",
                    "leaders": [
                        {
                            "athlete": {"displayName": "Drew Lock"},
                            "displayValue": "19/28, 175 YDS, 1 TD",
                        }
                    ],
                },
                {
                    "name": "rushingYards",
                    "leaders": [
                        {
                            "athlete": {"displayName": "Zach Charbonnet"},
                            "displayValue": "16 CAR, 77 YDS",
                        }
                    ],
                },
            ],
        }
    ],
}


def test_fetch_game_state_parses_header_linescores(monkeypatch):
    class FakeResp:
        def json(self):
            return _SUMMARY_PAYLOAD

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "gentlebot.cogs.seahawks_game_cog.requests.get",
        lambda url, timeout=10: FakeResp(),
    )

    cog = _make_cog(monkeypatch)
    state = cog.fetch_game_state("401873048")
    assert state["period"] == 4
    assert state["state"] == "post"
    assert state["sea_lines"] == [0, 14, 3, 0]
    assert state["opp_lines"] == [3, 0, 0, 0]
    assert state["sea_total"] == 17
    assert state["opp_total"] == 3
    assert state["last_play"] == "Q2 0:15 — AJ Barner 7 Yd pass from Drew Lock"


def test_final_summary_uses_header_score(monkeypatch):
    class FakeResp:
        def json(self):
            return _SUMMARY_PAYLOAD

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "gentlebot.cogs.seahawks_game_cog.requests.get",
        lambda url, timeout=10: FakeResp(),
    )

    cog = _make_cog(monkeypatch)
    summary = cog.fetch_game_summary("401873048")
    # The old code summed null boxscore linescores and reported a 0-0 tie
    # with 0 passing yards; the header says 17-3 with 175 net passing.
    assert summary["sea_score"] == 17
    assert summary["opp_score"] == 3
    assert summary["opp_name"] == "Arizona Cardinals"
    assert summary["sea_passing_yards"] == "175"
    assert summary["sea_rushing_yards"] == "120"
    assert summary["sea_total_yards"] == "295"
    assert summary["sea_qb"] == "Drew Lock"
    assert summary["sea_qb_stats"] == "19/28, 175 YDS, 1 TD"
    assert summary["sea_rb"] == "Zach Charbonnet"
    assert summary["sea_rb_stats"] == "16 CAR, 77 YDS"


def test_edits_message_after_every_score(monkeypatch):
    async def run_test():
        cog = _make_cog(monkeypatch)
        start = PST.localize(datetime(2024, 1, 1, 17, 30)).astimezone(timezone.utc)
        game = _game(start)
        monkeypatch.setattr(cog, "fetch_schedule", lambda: [game])
        monkeypatch.setattr(
            cog, "fetch_projection",
            lambda gid: {"sea_score": 24, "opp_score": 21, "sea_win": 0.55, "opp_win": 0.45},
        )

        channel = FakeChannel()
        monkeypatch.setattr(cog, "_sports_channel", lambda: channel)
        # Opener posts in the hour before kickoff.
        now = PST.localize(datetime(2024, 1, 1, 16, 35)).astimezone(timezone.utc)
        monkeypatch.setattr(cog, "_now", lambda: now)

        await cog._open_game_messages()
        assert len(channel.sent) == 1
        message = channel.sent[0]

        states = [
            _state(0, "pre", [], [], 0, 0),
            _state(1, "in", [7], [3], 7, 3, "8:12",
                   "Q1 8:12 — Fake TD pass"),
            _state(1, "in", [7], [3], 7, 3, "8:12",
                   "Q1 8:12 — Fake TD pass"),  # unchanged: no edit
            _state(1, "in", [10], [3], 10, 3, "2:01",
                   "Q1 2:01 — Fake field goal"),  # another score, same quarter
            _state(2, "in", [10, 0], [3, 10], 10, 13, "11:20",
                   "Q2 11:20 — Fake rushing TD"),
            _state(4, "post", [10, 0, 7, 3], [3, 10, 0, 7], 20, 20, "0:00"),
        ]
        state_iter = iter(states)

        def mock_state(gid):
            try:
                return next(state_iter)
            except StopIteration:
                return states[-1]

        monkeypatch.setattr(cog, "fetch_game_state", mock_state)
        monkeypatch.setattr(
            cog, "fetch_game_summary",
            lambda gid: {
                "sea_score": 20, "opp_score": 20,
                "opp_name": "Rams", "opp_abbr": "LAR",
                "sea_total_yards": "295", "opp_total_yards": "363",
                "sea_passing_yards": "175", "opp_passing_yards": "148",
                "sea_rushing_yards": "120", "opp_rushing_yards": "126",
                "sea_turnovers": "1", "opp_turnovers": "1",
            },
        )

        await cog._update_scores()  # pregame: no edit
        assert message.edits == []

        await cog._update_scores()  # Q1 7-3
        assert len(message.edits) == 1
        # The live score is the headline, ahead of the quarter lines.
        assert "## Seahawks 7 — Rams 3" in message.edits[-1]
        assert message.edits[-1].index("## Seahawks 7") < message.edits[-1].index("Q1:")
        assert "Q1: SEA 7 - LAR 3" in message.edits[-1]
        # No separate live line: the Last score line carries quarter + clock.
        assert "🟢 Live" not in message.edits[-1]
        assert "Last score: Q1 8:12 — Fake TD pass" in message.edits[-1]
        # The projection lives in the preview only; once live it's gone.
        assert "Projected:" not in message.edits[-1]

        await cog._update_scores()  # unchanged: still 1 edit
        assert len(message.edits) == 1

        await cog._update_scores()  # second score in Q1
        assert len(message.edits) == 2
        assert "## Seahawks 10 — Rams 3" in message.edits[-1]
        assert "Q1: SEA 10 - LAR 3" in message.edits[-1]

        await cog._update_scores()  # Q2
        assert len(message.edits) == 3
        assert "## Seahawks 10 — Rams 13" in message.edits[-1]
        assert "Q2: SEA 0 - LAR 10" in message.edits[-1]

        await cog._update_scores()  # final: summary edited in, game done
        assert len(message.edits) == 4
        assert "🤝 **TIE GAME**" in message.edits[-1]
        assert "Final Score:** Seahawks 20 - Rams 20" in message.edits[-1]
        assert "Passing: SEA 175 | LAR 148" in message.edits[-1]
        assert "Projected score:" not in message.edits[-1]
        assert "g1" in cog.done
        assert "g1" not in cog.messages

        await cog._update_scores()  # done: no further edits
        assert len(message.edits) == 4
        assert len(channel.sent) == 1  # no duplicate message posted

    asyncio.run(run_test())


def test_recovers_message_after_restart(monkeypatch):
    async def run_test():
        cog = _make_cog(monkeypatch)
        now = PST.localize(datetime(2024, 1, 1, 19, 30)).astimezone(timezone.utc)
        start = PST.localize(datetime(2024, 1, 1, 17, 30)).astimezone(timezone.utc)
        game = _game(start)
        monkeypatch.setattr(cog, "fetch_schedule", lambda: [game])
        monkeypatch.setattr(cog, "_now", lambda: now)

        # The 9 AM opener, as it sits in channel history after a restart.
        opener = FakeMessage(
            "🏈 LAR @ SEA — Mon 1/1, 5:30 PM PT\n"
            "Projected score: Seahawks 24 - Rams 21\n"
            "Win odds: Seahawks 55.0%, Rams 45.0%\n"
            "\n"
            "Live score updates will land here as the game goes."
        )
        channel = FakeChannel(history_msgs=[opener])
        monkeypatch.setattr(cog, "_sports_channel", lambda: channel)

        monkeypatch.setattr(
            cog, "fetch_game_state",
            lambda gid: _state(1, "in", [7], [3], 7, 3, "8:12",
                               "Q1 8:12 — Fake TD pass"),
        )

        await cog._update_scores()
        # Adopted the existing message (no fresh post) and edited it live.
        assert len(channel.sent) == 0
        assert cog.messages["g1"] is opener
        assert len(opener.edits) == 1
        assert "Q1: SEA 7 - LAR 3" in opener.edits[0]

    asyncio.run(run_test())
