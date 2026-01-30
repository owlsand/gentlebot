"""Utility functions for daily digest features."""

from __future__ import annotations


def assign_tiers(rankings: list[int], roles: dict[str, int]) -> dict[int, int]:
    """Return user→role mapping for tiered badges using fixed ranges."""
    result: dict[int, int] = {}
    tiers = (
        ("gold", 0, 1),    # top 1
        ("silver", 1, 2),  # next 1
        ("bronze", 2, 4),  # next 2
    )
    for name, start, end in tiers:
        role_id = roles.get(name, 0)
        for idx in range(start, min(end, len(rankings))):
            result[rankings[idx]] = role_id
    return result
