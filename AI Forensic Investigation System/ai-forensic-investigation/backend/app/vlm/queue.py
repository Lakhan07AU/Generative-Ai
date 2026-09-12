"""Per-session rate limiting for live VLM requests (Phase 4 cost control)."""

from __future__ import annotations

import threading
import time
from typing import Optional


class VlmRateLimiter:
    """Per-session gate: hard request cap + cooldown between provider calls.

    Thread-safe. Used by the session enqueue path only (producer side); the
    worker itself is single-threaded per session (concurrency = 1).
    """

    def __init__(
        self,
        max_requests: Optional[int] = None,
        cooldown_seconds: Optional[float] = None,
        clock=None,
    ) -> None:
        self._max_requests = max_requests
        self._cooldown = float(cooldown_seconds or 0.0)
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._request_count = 0
        self._last_request_at: Optional[float] = None

    def allow(self, now: Optional[float] = None) -> bool:
        """Reserve one request slot; returns True when permitted."""
        with self._lock:
            now = now if now is not None else self._clock()
            if self._max_requests is not None and self._request_count >= self._max_requests:
                return False
            if (
                self._cooldown
                and self._last_request_at is not None
                and (now - self._last_request_at) < self._cooldown
            ):
                return False
            self._request_count += 1
            self._last_request_at = now
            return True

    def cooldown_active(self, now: Optional[float] = None) -> bool:
        with self._lock:
            now = now if now is not None else self._clock()
            return bool(
                self._cooldown
                and self._last_request_at is not None
                and (now - self._last_request_at) < self._cooldown
            )

    def requests_used(self) -> int:
        with self._lock:
            return self._request_count

    def last_request_at(self) -> Optional[float]:
        with self._lock:
            return self._last_request_at