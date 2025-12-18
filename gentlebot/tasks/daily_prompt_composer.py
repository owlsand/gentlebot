"""Daily prompt generation system for Gentlebot.

This module builds varied daily prompts using a configurable library of
templates, tones, constraints, and twists. It enforces cooldowns and novelty
checks before persisting the selected prompt to a SQLite database.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import random
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("gentlebot.tasks.daily_prompt_composer")


DEFAULT_CONFIG_PATH = Path(__file__).with_name("daily_prompt_config.yaml")
DEFAULT_STATE_PATH = Path("db") / "daily_prompts.sqlite"


@dataclasses.dataclass
class CandidatePrompt:
    """Container for candidate prompt metadata."""

    date: dt.date
    topic_bucket: str
    template_id: str
    format: str
    tone: str
    constraint: str
    twist: str
    prompt_text: str
    score: float
    length: int
    signature: str


class DailyPromptComposer:
    """Compose daily prompts with cooldowns and novelty checks."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        state_path: str | Path | None = None,
    ) -> None:
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.state_path = Path(state_path) if state_path else DEFAULT_STATE_PATH
        self.config = self._load_config(self.config_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.state_path)
        self.conn.row_factory = sqlite3.Row
        self._ensure_table()

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        try:
            self.conn.close()
        except Exception:  # pragma: no cover - defensive cleanup
            log.exception("Failed to close daily prompt composer connection")

    def __enter__(self) -> "DailyPromptComposer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ─── Public API ──────────────────────────────────────────────────────
    def generate_prompt(self, date: dt.date | None = None, k: int | None = None) -> CandidatePrompt:
        """Generate, select, persist, and return a prompt for ``date``.

        Args:
            date: Target date for the prompt. Defaults to today.
            k: Number of candidates to sample before selection.
        """

        target_date = date or dt.date.today()
        candidates = self.generate_candidates(k=k, date=target_date)
        best = self.select_best(candidates)
        self.persist(best)
        return best

    def generate_candidates(self, k: int | None = None, date: dt.date | None = None) -> list[CandidatePrompt]:
        """Return candidate prompts that pass cooldown and novelty filters."""

        target_date = date or dt.date.today()
        cfg = self.config
        desired = k or int(cfg.get("generation", {}).get("candidate_count", 20))
        rng = self._build_rng(cfg, target_date)
        history = self._fetch_history(cfg.get("similarity", {}).get("history_size", 30))
        cooldowns = cfg.get("cooldowns", {})

        candidates: list[CandidatePrompt] = []
        attempts = 0
        max_attempts = desired * 10
        while len(candidates) < desired and attempts < max_attempts:
            attempts += 1
            topic = self._sample_with_cooldown(
                rng,
                cfg.get("topics", {}),
                cooldowns.get("topic_days", 5),
                target_date,
                history,
                "topic_bucket",
            )
            template = self._choose_template(topic, history, target_date, rng)
            if not template:
                continue
            tone = self._sample_with_cooldown(
                rng,
                self._tone_weights(template, cfg),
                cooldowns.get("tone_days", 3),
                target_date,
                history,
                "tone",
            )
            constraint = self._sample_with_cooldown(
                rng,
                cfg.get("constraints", {}),
                cooldowns.get("constraint_days", 10),
                target_date,
                history,
                "constraint_label",
            )
            twist = self._sample_with_cooldown(
                rng,
                cfg.get("twists", {}),
                cooldowns.get("twist_days", 10),
                target_date,
                history,
                "twist",
            )

            base_text = self._fill_template(template, rng)
            constraint_text = self._lookup_text(cfg.get("constraints", {}), constraint)
            twist_text = self._lookup_text(cfg.get("twists", {}), twist)
            prompt_text = self._assemble_prompt(base_text, constraint_text, twist_text)
            length = len(prompt_text)
            signature = self._ngram_signature(prompt_text)

            candidate = CandidatePrompt(
                date=target_date,
                topic_bucket=topic,
                template_id=template["id"],
                format=template["format"],
                tone=tone,
                constraint=constraint,
                twist=twist,
                prompt_text=prompt_text,
                score=0.0,
                length=length,
                signature=signature,
            )

            if not self._passes_hard_filters(candidate, template, history):
                continue
            candidate.score = self.score_candidate(candidate, history)
            candidates.append(candidate)

        if not candidates:
            raise RuntimeError("No viable prompt candidates after filtering")
        return candidates

    def score_candidate(self, candidate: CandidatePrompt, history: list[sqlite3.Row]) -> float:
        """Return a soft score favoring diversity while penalizing similarity."""

        similarity_penalty = self._max_similarity(candidate, history) * -1.0
        diversity_bonus = self._diversity_bonus(candidate, history)
        base = 1.0 if candidate.length <= self.config.get("length", {}).get("max", 350) else 0.0
        return base + similarity_penalty + diversity_bonus

    @staticmethod
    def select_best(candidates: Iterable[CandidatePrompt]) -> CandidatePrompt:
        return max(candidates, key=lambda c: c.score)

    def persist(self, candidate: CandidatePrompt) -> None:
        """Persist the chosen candidate to the SQLite table."""

        now = dt.datetime.utcnow().isoformat()
        self.conn.execute(
            """
            INSERT INTO daily_prompts (
                date,
                topic_bucket,
                template_id,
                format,
                tone,
                constraint_label,
                twist,
                prompt_text,
                created_at,
                ngram_signature,
                length
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.date.isoformat(),
                candidate.topic_bucket,
                candidate.template_id,
                candidate.format,
                candidate.tone,
                candidate.constraint,
                candidate.twist,
                candidate.prompt_text,
                now,
                candidate.signature,
                candidate.length,
            ),
        )
        self.conn.commit()

    # ─── Candidate helpers ───────────────────────────────────────────────
    def _build_rng(self, cfg: dict[str, Any], target_date: dt.date) -> random.Random:
        deterministic = cfg.get("generation", {}).get("deterministic_by_date", True)
        seed_override = cfg.get("generation", {}).get("seed")
        seed_value = seed_override if seed_override is not None else int(target_date.strftime("%Y%m%d"))
        return random.Random(seed_value if deterministic else None)

    def _fetch_history(self, limit: int) -> list[sqlite3.Row]:
        cursor = self.conn.execute(
            "SELECT * FROM daily_prompts ORDER BY date DESC, created_at DESC LIMIT ?",
            (limit,),
        )
        return list(cursor.fetchall())

    def _sample_with_cooldown(
        self,
        rng: random.Random,
        pool: dict[str, Any],
        cooldown_days: int,
        target_date: dt.date,
        history: list[sqlite3.Row],
        column_name: str,
    ) -> str:
        weights = {}
        for key, value in pool.items():
            weight = value if isinstance(value, (int, float)) else value.get("weight", 1.0)
            last_used = self._last_used(history, column_name, key)
            if last_used and (target_date - last_used).days < cooldown_days:
                weight = 0.0
            weights[key] = weight
        if all(w <= 0 for w in weights.values()):
            weights = {k: (v if isinstance(v, (int, float)) else v.get("weight", 1.0)) for k, v in pool.items()}
        return self._weighted_choice(weights, rng)

    def _choose_template(
        self,
        topic: str,
        history: list[sqlite3.Row],
        target_date: dt.date,
        rng: random.Random,
    ) -> dict[str, Any] | None:
        cooldown_days = self.config.get("cooldowns", {}).get("template_days", 21)
        allow_sensitive = bool(self.config.get("flags", {}).get("allow_sensitive", False))
        templates: list[dict[str, Any]] = self.config.get("templates", [])
        eligible: list[tuple[dict[str, Any], float]] = []
        for tpl in templates:
            if topic not in tpl.get("allowed_topics", []):
                continue
            if tpl.get("flags") and "avoid_sensitive" in tpl["flags"] and not allow_sensitive:
                continue
            cooldown_override = tpl.get("cooldown_days", cooldown_days)
            last_used = self._last_used(history, "template_id", tpl["id"])
            if last_used and (target_date - last_used).days < cooldown_override:
                continue
            eligible.append((tpl, float(tpl.get("weight", 1.0))))
        if not eligible:
            return None
        return self._weighted_choice_dict(eligible, rng)

    @staticmethod
    def _tone_weights(template: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
        template_tones = template.get("compatible_tones") or list(cfg.get("tones", {}).keys())
        return {tone: cfg.get("tones", {}).get(tone, 1.0) for tone in template_tones}

    def _fill_template(self, template: dict[str, Any], rng: random.Random) -> str:
        pools: dict[str, list[str]] = template.get("variable_pools", {})
        values = {name: rng.choice(options) for name, options in pools.items() if options}
        try:
            return template["base_text"].format(**values)
        except KeyError as exc:  # pragma: no cover - defensive
            missing = exc.args[0]
            raise ValueError(f"Missing placeholder value for '{missing}' in template {template['id']}")

    @staticmethod
    def _assemble_prompt(base: str, constraint: str | None, twist: str | None) -> str:
        parts = [base.rstrip()]
        if constraint:
            parts.append(constraint.strip())
        if twist:
            parts.append(twist.strip())
        return " ".join(parts)

    def _passes_hard_filters(
        self,
        candidate: CandidatePrompt,
        template: dict[str, Any],
        history: list[sqlite3.Row],
    ) -> bool:
        cfg = self.config
        length_cfg = cfg.get("length", {})
        min_len = template.get("length_bounds", {}).get("min", length_cfg.get("min", 200))
        max_len = template.get("length_bounds", {}).get("max", length_cfg.get("max", 350))
        if candidate.length < min_len or candidate.length > max_len:
            return False

        banned = [p.lower() for p in cfg.get("banned_phrases", [])]
        lowered = candidate.prompt_text.lower()
        if any(bad in lowered for bad in banned):
            return False

        if not self._passes_similarity(candidate, history):
            return False

        sensitive_flagged = template.get("flags") and "avoid_sensitive" in template["flags"]
        if sensitive_flagged and not cfg.get("flags", {}).get("allow_sensitive", False):
            return False
        return True

    def _passes_similarity(self, candidate: CandidatePrompt, history: list[sqlite3.Row]) -> bool:
        similarity_cfg = self.config.get("similarity", {})
        threshold = float(similarity_cfg.get("threshold", 0.82))
        mode = similarity_cfg.get("mode", "ngram")
        if mode == "embedding":
            log.debug("Embedding mode selected but embedding generation is unavailable; falling back to n-grams")
        max_sim = self._max_similarity(candidate, history)
        return max_sim < threshold

    # ─── Scoring helpers ──────────────────────────────────────────────────
    def _max_similarity(self, candidate: CandidatePrompt, history: list[sqlite3.Row]) -> float:
        if not history:
            return 0.0
        cand_sig = set(candidate.signature.split("|"))
        max_sim = 0.0
        for row in history:
            hist_sig = set(str(row["ngram_signature"]).split("|"))
            sim = self._jaccard(cand_sig, hist_sig)
            max_sim = max(max_sim, sim)
        return max_sim

    def _diversity_bonus(self, candidate: CandidatePrompt, history: list[sqlite3.Row]) -> float:
        if not history:
            return 0.5
        bonus = 0.0
        recent = history[:1]
        recent_week = history[:7]
        if all(row["topic_bucket"] != candidate.topic_bucket for row in recent):
            bonus += 0.3
        if all(row["format"] != candidate.format for row in recent_week):
            bonus += 0.2
        if all(row["tone"] != candidate.tone for row in recent_week):
            bonus += 0.1
        return bonus

    # ─── Utilities ────────────────────────────────────────────────────────
    @staticmethod
    def _ngram_signature(text: str, n: int = 3) -> str:
        normalized = re.sub(r"\s+", " ", text.lower())
        grams = {normalized[i : i + n] for i in range(len(normalized) - n + 1)}
        return "|".join(sorted(grams))

    @staticmethod
    def _jaccard(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    @staticmethod
    def _lookup_text(pool: dict[str, Any], key: str) -> str | None:
        entry = pool.get(key, {}) if isinstance(pool.get(key), dict) else None
        if isinstance(entry, dict):
            return entry.get("text")
        return None

    def _last_used(
        self, history: list[sqlite3.Row], column_name: str, value: str
    ) -> dt.date | None:
        for row in history:
            if row[column_name] == value:
                return dt.date.fromisoformat(str(row["date"]))
        return None

    @staticmethod
    def _weighted_choice(weights: dict[str, float], rng: random.Random) -> str:
        filtered = {k: w for k, w in weights.items() if w > 0}
        if not filtered:
            raise RuntimeError("No available options after applying cooldowns")
        total = sum(filtered.values())
        r = rng.uniform(0, total)
        upto = 0.0
        for key, weight in filtered.items():
            upto += weight
            if upto >= r:
                return key
        return next(iter(filtered))

    @staticmethod
    def _weighted_choice_dict(options: list[tuple[dict[str, Any], float]], rng: random.Random) -> dict[str, Any]:
        total = sum(weight for _, weight in options)
        r = rng.uniform(0, total)
        upto = 0.0
        for tpl, weight in options:
            upto += weight
            if upto >= r:
                return tpl
        return options[-1][0]

    @staticmethod
    def _load_config(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data or {}

    def _ensure_table(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                topic_bucket TEXT NOT NULL,
                template_id TEXT NOT NULL,
                format TEXT NOT NULL,
                tone TEXT NOT NULL,
                constraint_label TEXT NOT NULL,
                twist TEXT NOT NULL,
                prompt_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                ngram_signature TEXT,
                length INTEGER,
                engagement_score REAL,
                embedding_vector BLOB
            )
            """
        )
        self.conn.commit()

