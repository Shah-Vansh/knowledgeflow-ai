"""
In-memory sliding-window rate limiter.

Limits are PER PROCESS: with several uvicorn workers each one counts separately,
and a restart forgets everything. Good enough for one machine; a shared store
(PostgreSQL or Redis) would be needed for several.
"""
import math
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Tuple

WINDOW_SECONDS = 60.0
_MAX_KEYS = 50_000


class SlidingWindowLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float = WINDOW_SECONDS) -> Tuple[bool, int]:
        """Records one request. Returns (allowed, retry_after_seconds)."""
        if limit <= 0:
            return False, int(window)
        now = self._clock()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= _MAX_KEYS:
                    self._prune(now, window)
                hits = self._hits[key] = deque()
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, math.ceil(hits[0] + window - now))
                return False, retry_after
            hits.append(now)
            return True, 0

    def _prune(self, now: float, window: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - window]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def reset() -> None:
    limiter.reset()
