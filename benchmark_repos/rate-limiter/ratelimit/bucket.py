"""Fixed-window rate limiter. Bug: when a window expires the request count is
reset but the window start time is never advanced, so after the first window
the limiter grants a fresh bucket on *every* request — unlimited throughput."""

from __future__ import annotations

import time
from typing import Callable


class RateLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._now = now or time.time
        self._window_start: dict[str, float] = {}
        self._count: dict[str, int] = {}

    def is_allowed(self, key: str) -> bool:
        """Return True if a request under `key` is within the window budget.

        Bug: once a window expires the request count is reset, but the new
        window start is never recorded, so every later request also gets a
        fresh bucket — the limiter becomes effectively unlimited.
        """
        now = self._now()
        if key not in self._window_start:
            self._window_start[key] = now
        start = self._window_start[key]
        if now - start >= self.window_seconds:
            self._count[key] = 0
        if self._count.get(key, 0) < self.max_requests:
            self._count[key] = self._count.get(key, 0) + 1
            return True
        return False