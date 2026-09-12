"""Bounded, thread-safe, timestamped rolling frame buffer (Phase 1 ingest)."""

import threading
import time
from collections import deque
from typing import Deque, List, Optional


class FrameEntry:
    """A single buffered frame with its capture timestamp and arrival order."""

    __slots__ = ("frame", "timestamp", "sequence")

    def __init__(self, frame, timestamp: float, sequence: int):
        self.frame = frame
        self.timestamp = float(timestamp)
        self.sequence = sequence


class RollingFrameBuffer:
    """Bounded rolling buffer of the most recent sampled frames.

    The buffer keeps sampled frames from the last ``window_seconds`` of live
    footage (10-30s typical) and never exceeds ``max_frames`` entries. When the
    budget is exceeded the OLDEST frame is discarded (strict FIFO eviction);
    frames older than the rolling window are discarded on every append/trim.

    Concurrency: every mutating method is guarded by a ``threading.RLock`` so
    concurrent writers (a WebRTC receive task, a simulation feeder thread, and
    REST status readers) are safe. A caller-supplied ``clock`` lets tests drive
    window eviction deterministically.
    """

    def __init__(
        self,
        window_seconds: float = 15.0,
        max_frames: int = 150,
        clock=None,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if max_frames <= 0:
            raise ValueError("max_frames must be > 0")
        self._window_seconds = float(window_seconds)
        self._max_frames = int(max_frames)
        self._clock = clock or time.time
        self._entries: Deque[FrameEntry] = deque()
        self._lock = threading.RLock()
        self._sequence = 0

    # ------------------------------------------------------------------ props

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    @property
    def max_frames(self) -> int:
        return self._max_frames

    @property
    def oldest_timestamp(self) -> Optional[float]:
        with self._lock:
            if not self._entries:
                return None
            return self._entries[0].timestamp

    @property
    def newest_timestamp(self) -> Optional[float]:
        with self._lock:
            if not self._entries:
                return None
            return self._entries[-1].timestamp

    # -------------------------------------------------------------- mutation

    def append(self, frame, timestamp: float) -> int:
        """Append a sampled frame; returns the number of frames evicted (0+)."""
        with self._lock:
            self._sequence += 1
            self._entries.append(FrameEntry(frame, timestamp, self._sequence))
            return self._evict_locked()

    def trim(self) -> int:
        """Drop frames outside the rolling window / budget; returns evicted."""
        with self._lock:
            return self._evict_locked()

    def _evict_locked(self) -> int:
        evicted = 0
        cutoff = self._clock() - self._window_seconds
        while self._entries:
            over_budget = len(self._entries) > self._max_frames
            too_old = self._entries[0].timestamp < cutoff
            if not over_budget and not too_old:
                break
            self._entries.popleft()
            evicted += 1
        return evicted

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    # ---------------------------------------------------------------- reads

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def latest(self) -> Optional[FrameEntry]:
        with self._lock:
            if not self._entries:
                return None
            return self._entries[-1]

    def frames_between(self, start_ts: float, end_ts: float) -> List[FrameEntry]:
        """Return a snapshot of frames with ``start_ts <= timestamp <= end_ts``
        in arrival order (oldest first). Safe to hold past frames."""
        with self._lock:
            return [
                entry
                for entry in self._entries
                if start_ts <= entry.timestamp <= end_ts
            ]

    def snapshot(self, limit: Optional[int] = None) -> List[FrameEntry]:
        """Return a copy of the buffered entries (oldest first)."""
        with self._lock:
            items = list(self._entries)
        if limit is not None and len(items) > limit:
            items = items[-limit:]
        return items

    def __len__(self) -> int:
        return self.count()