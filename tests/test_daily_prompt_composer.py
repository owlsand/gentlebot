from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path

import pytest
import yaml

from gentlebot.tasks.daily_prompt_composer import CandidatePrompt, DailyPromptComposer


def _write_config(tmp_path: Path, overrides: dict | None = None) -> Path:
    base = {
        "generation": {"candidate_count": 5, "deterministic_by_date": True},
        "length": {"min": 0, "max": 400},
        "cooldowns": {
            "template_days": 21,
            "topic_days": 5,
            "tone_days": 3,
            "constraint_days": 10,
            "twist_days": 10,
        },
        "similarity": {"mode": "ngram", "threshold": 0.75, "history_size": 10},
        "flags": {"allow_sensitive": False},
        "banned_phrases": [],
        "topics": {"alpha": 1.0, "beta": 1.0},
        "formats": {"poll": 1.0},
        "tones": {"calm": 1.0},
        "constraints": {"none": {"text": "", "weight": 1.0}},
        "twists": {"none": {"text": "", "weight": 1.0}},
        "templates": [
            {
                "id": "alpha_template",
                "format": "poll",
                "allowed_topics": ["alpha"],
                "compatible_tones": ["calm"],
                "base_text": "Alpha prompt about {item}.",
                "variable_pools": {"item": ["tea", "coffee"]},
                "length_bounds": {"min": 10, "max": 280},
            },
            {
                "id": "beta_template",
                "format": "poll",
                "allowed_topics": ["beta"],
                "compatible_tones": ["calm"],
                "base_text": "Beta prompt about {item}.",
                "variable_pools": {"item": ["rain", "sun"]},
                "length_bounds": {"min": 10, "max": 280},
            },
        ],
    }
    if overrides:
        base.update(overrides)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    return path


def _composer(tmp_path: Path, overrides: dict | None = None) -> DailyPromptComposer:
    config_path = _write_config(tmp_path, overrides)
    state_path = tmp_path / "state.sqlite"
    return DailyPromptComposer(config_path=config_path, state_path=state_path)


def test_cooldown_blocks_recent_topic(tmp_path: Path) -> None:
    composer = _composer(tmp_path)
    recent_date = dt.date.today() - dt.timedelta(days=1)
    past_prompt = CandidatePrompt(
        date=recent_date,
        topic_bucket="alpha",
        template_id="alpha_template",
        format="poll",
        tone="calm",
        constraint="none",
        twist="none",
        prompt_text="Alpha prompt about tea.",
        score=1.0,
        length=23,
        signature=composer._ngram_signature("Alpha prompt about tea."),
    )
    composer.persist(past_prompt)

    candidate = composer.generate_prompt(date=dt.date.today(), k=3)
    assert candidate.topic_bucket == "beta"
    assert candidate.template_id == "beta_template"


def test_similarity_filter_prefers_new_template(tmp_path: Path) -> None:
    composer = _composer(tmp_path)
    recent_date = dt.date.today() - dt.timedelta(days=2)
    duplicate_prompt = CandidatePrompt(
        date=recent_date,
        topic_bucket="alpha",
        template_id="alpha_template",
        format="poll",
        tone="calm",
        constraint="none",
        twist="none",
        prompt_text="Alpha prompt about tea.",
        score=1.0,
        length=23,
        signature=composer._ngram_signature("Alpha prompt about tea."),
    )
    composer.persist(duplicate_prompt)

    candidate = composer.generate_prompt(date=dt.date.today(), k=5)
    assert candidate.template_id == "beta_template"


def test_template_filling_uses_variable_pool(tmp_path: Path) -> None:
    composer = _composer(tmp_path)
    candidate = composer.generate_prompt(date=dt.date.today(), k=3)
    assert "{" not in candidate.prompt_text
    assert "}" not in candidate.prompt_text


def test_generation_is_deterministic_by_date(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    state_one = tmp_path / "state_one.sqlite"
    state_two = tmp_path / "state_two.sqlite"
    composer_one = DailyPromptComposer(config_path=config_path, state_path=state_one)
    composer_two = DailyPromptComposer(config_path=config_path, state_path=state_two)
    target_date = dt.date(2024, 1, 1)

    first = composer_one.generate_prompt(date=target_date, k=2)
    second = composer_two.generate_prompt(date=target_date, k=2)

    assert dataclasses.asdict(first) == dataclasses.asdict(second)

