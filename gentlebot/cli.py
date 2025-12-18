"""Lightweight CLI for Gentlebot utilities."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json

from .tasks.daily_prompt_composer import DailyPromptComposer


def _parse_date(value: str | None) -> dt.date:
    if not value:
        return dt.date.today()
    return dt.date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gentlebot CLI")
    subparsers = parser.add_subparsers(dest="command")

    prompt_parser = subparsers.add_parser(
        "generate-prompt", help="Generate and persist a daily prompt"
    )
    prompt_parser.add_argument("--date", help="Target date (YYYY-MM-DD)")
    prompt_parser.add_argument(
        "--config", help="Path to prompt config YAML", default=None
    )
    prompt_parser.add_argument(
        "--state", help="Path to SQLite state file", default=None
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command != "generate-prompt":
        parser.error("Please supply a command. Try --help for options.")

    date = _parse_date(args.date)
    with DailyPromptComposer(config_path=args.config, state_path=args.state) as composer:
        prompt = composer.generate_prompt(date=date)
        print(json.dumps(dataclasses.asdict(prompt), indent=2, default=str))


if __name__ == "__main__":
    main()

