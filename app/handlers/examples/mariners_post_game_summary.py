"""Example handler demonstrating idempotency best practices."""
from __future__ import annotations

from typing import Dict

from ..interface import RetryableError, TaskContext

_POSTED_MARKERS: Dict[str, int] = {}
_ATTEMPTS: Dict[str, int] = {}


def run_task(ctx: TaskContext, payload: Dict[str, str]) -> Dict[str, str]:
    """Pretend to post a Discord summary for the Seattle Mariners."""

    team = payload.get("team", "SEA")
    game_id = payload.get("game_id")
    if not game_id:
        raise RetryableError("No final game yet")

    marker_key = f"{team}:{game_id}"
    _ATTEMPTS[marker_key] = _ATTEMPTS.get(marker_key, 0) + 1

    if payload.get("fail_once") and _ATTEMPTS[marker_key] == 1:
        raise RetryableError("box score not ready")

    if marker_key in _POSTED_MARKERS:
        return {"status": "noop", "reason": "duplicate", "attempts": str(_ATTEMPTS[marker_key])}

    _POSTED_MARKERS[marker_key] = ctx["occurrence_id"]
    return {"status": "posted", "occurrence_id": str(ctx["occurrence_id"]), "attempts": str(_ATTEMPTS[marker_key])}
