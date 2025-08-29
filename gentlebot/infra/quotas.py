"""Simple in-process quota guards."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict


class RateLimited(Exception):
    """Raised when a quota is exceeded."""


def _now() -> float:
    return time.time()


@dataclass
class Limit:
    rpm: int | None = None
    tpm: int | None = None
    rpd: int | None = None


class QuotaGuard:
    def __init__(self, limits: Dict[str, Limit]):
        self.limits = limits
        self.req_hist: Dict[str, deque[float]] = defaultdict(deque)
        self.tok_hist: Dict[str, deque[tuple[float, int]]] = defaultdict(deque)
        self.daily: Dict[str, tuple[float, int]] = defaultdict(lambda: (_now(), 0))

    def check(self, route: str, tokens: int) -> float:
        """Check quotas for *route*. Return temperature delta."""
        now = _now()
        limit = self.limits.get(route)
        if not limit:
            return 0.0

        # RPM
        if limit.rpm is not None:
            hist = self.req_hist[route]
            while hist and hist[0] <= now - 60:
                hist.popleft()
            if len(hist) >= limit.rpm:
                raise RateLimited
            hist.append(now)
            if len(hist) >= 0.9 * limit.rpm:
                return -0.2

        # TPM
        if limit.tpm is not None:
            thist = self.tok_hist[route]
            while thist and thist[0][0] <= now - 60:
                thist.popleft()
            used = sum(t for _, t in thist)
            if used + tokens > limit.tpm:
                raise RateLimited
            thist.append((now, tokens))
            if used + tokens >= 0.9 * limit.tpm:
                return -0.2

        # RPD
        if limit.rpd is not None:
            day_start, count = self.daily[route]
            if now - day_start >= 86400:
                day_start, count = now, 0
            if count + 1 > limit.rpd:
                raise RateLimited
            count += 1
            self.daily[route] = (day_start, count)
            if count >= 0.9 * limit.rpd:
                return -0.2

        return 0.0
