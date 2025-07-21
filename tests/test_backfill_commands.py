import types
import discord

from gentlebot.backfill_commands import _extract_cmd


def test_extract_cmd_interaction_metadata():
    msg = types.SimpleNamespace(content="irrelevant", interaction_metadata=types.SimpleNamespace(name="foo"))
    assert _extract_cmd(msg) == "foo"


def test_extract_cmd_fallback():
    msg = types.SimpleNamespace(content="/bar baz", interaction=None)
    assert _extract_cmd(msg) == "bar"
