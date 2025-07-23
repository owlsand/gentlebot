from gentlebot.backfill_reactions import parse_args


def test_parse_args_env(monkeypatch):
    monkeypatch.setenv("BACKFILL_DAYS", "42")
    args = parse_args([])
    assert args.days == 42
