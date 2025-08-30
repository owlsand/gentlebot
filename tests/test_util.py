import pytest

from types import SimpleNamespace

from gentlebot.util import chan_name, guild_name, rows_from_tag, user_name

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
