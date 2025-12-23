import pytest

from types import SimpleNamespace

from gentlebot.util import bool_env, chan_name, guild_name, rows_from_tag, user_name

@pytest.mark.parametrize("tag,expected", [
    ("INSERT 0 1", 1),
    ("INSERT 0 0", 0),
    ("UPDATE 5", 5),
    ("bogus", 0),
])
def test_rows_from_tag(tag, expected):
    assert rows_from_tag(tag) == expected


def test_user_name_display_preferred():
    obj = SimpleNamespace(display_name="Tester", id=42)
    assert user_name(obj) == "Tester"


def test_chan_name_prefixes_hash():
    chan = SimpleNamespace(name="general")
    assert chan_name(chan) == "#general"


def test_guild_name_from_name():
    guild = SimpleNamespace(name="Gentlefolk")
    assert guild_name(guild) == "Gentlefolk"


def test_bool_env_true(monkeypatch):
    monkeypatch.setenv("BOOL_ENV_TRUE_TEST", "TrUe")
    assert bool_env("BOOL_ENV_TRUE_TEST") is True


def test_bool_env_invalid_logs(monkeypatch, caplog):
    monkeypatch.setenv("BOOL_ENV_INVALID_TEST", "maybe")
    with caplog.at_level("WARNING"):
        assert bool_env("BOOL_ENV_INVALID_TEST", default=False) is False
    assert "Invalid boolean for BOOL_ENV_INVALID_TEST" in caplog.text
