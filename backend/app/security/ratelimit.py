import math
import time
from collections import defaultdict, deque
from threading import Lock

from slowapi import Limiter
from slowapi.util import get_remote_address

GLOBAL_LIMIT = "300/minute"
REGISTER_LIMIT = "5/hour"

limiter = Limiter(key_func=get_remote_address, default_limits=[GLOBAL_LIMIT])


class FailedAttemptTracker:
    """Counts failed sign-ins per IP in a sliding window; successful sign-ins never count."""

    def __init__(self, max_failures: int = 5, window_s: int = 15 * 60) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] >= self.window_s:
            q.popleft()
        return q

    def retry_after_minutes(self, key: str) -> int | None:
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if len(q) < self.max_failures:
                return None
            return max(1, math.ceil((self.window_s - (now - q[0])) / 60))

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._failures[key].append(time.monotonic())

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


signin_failures = FailedAttemptTracker()
