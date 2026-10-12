"""A small in-process sliding-window limiter for cheap, high-frequency calls.

Used for document searches (each embeds one short query with the model provider). It lives in the
API process's memory, so with several API instances the effective allowance is per instance: that is
enough to stop a runaway client from running up model calls, which is its only job. Anything that
must be exact (daily job allowances) is counted in the database instead.
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from uuid import UUID


class SlidingWindowLimiter:
    def __init__(
        self, limit: int, window_seconds: float, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: defaultdict[UUID, deque[float]] = defaultdict(deque)

    def allow(self, key: UUID) -> bool:
        """Record one use and say whether it is within the allowance."""
        now = self._clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        if len(self._hits) > 10_000:  # bound memory: forget learners with nothing recent
            for stale in [k for k, v in self._hits.items() if not v]:
                del self._hits[stale]
        return True

    def retry_after(self, key: UUID) -> int:
        """Seconds until the oldest use leaves the window (at least 1)."""
        hits = self._hits.get(key)
        if not hits:
            return 1
        return max(1, int(self._window - (self._clock() - hits[0])) + 1)
