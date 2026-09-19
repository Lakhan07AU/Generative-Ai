"""In-process sliding-window rate limiter for credential endpoints (Phase 9).

A tiny, dependency-free sliding-window counter keyed by ``ident`` (the caller's
IP plus the login email). Successful authentication clears the bucket; repeated
failures stagger with an increasing retry window so a credential-stuffing burst
is throttled without persisting user data. Suitable for a single-process demo
deployment; a multi-worker deployment should move this to a shared store
(e.g. Redis), which the interface below makes straightforward.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict


@dataclass
class _Bucket:
    hits: Deque[float] = field(default_factory=deque)
    locked_until: float = 0.0


class SlidingWindowRateLimiter:
    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self._max_attempts = max(1, int(max_attempts))
        self._window_seconds = max(0.1, float(window_seconds))
        self._buckets: Dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _prune(self, bucket: _Bucket, now: float) -> None:
        while bucket.hits and bucket.hits[0] < now - self._window_seconds:
            bucket.hits.popleft()

    def check(self, ident: str) -> bool:
        """Whether a request for ``ident`` is still allowed right now."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.setdefault(ident, _Bucket())
            self._prune(bucket, now)
            if bucket.locked_until > now:
                return False
            return len(bucket.hits) < self._max_attempts

    def retry_after(self, ident: str) -> int:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(ident)
            if bucket is None:
                return 0
            if bucket.locked_until > now:
                return max(1, int(bucket.locked_until - now) + 1)
            return max(1, int(self._window_seconds))

    def hit(self, ident: str) -> int:
        """Record a failed attempt; returns the current failure count."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.setdefault(ident, _Bucket())
            self._prune(bucket, now)
            bucket.hits.append(now)
            count = len(bucket.hits)
            if count >= self._max_attempts:
                # 60s base lockout, doubling per extra violation, capped at 15 min.
                bucket.locked_until = now + min(
                    900.0, 60.0 * (2 ** (count // self._max_attempts - 1))
                )
            return count

    def reset(self, ident: str) -> None:
        with self._lock:
            self._buckets.pop(ident, None)