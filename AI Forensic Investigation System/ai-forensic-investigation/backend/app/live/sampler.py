"""Configurable, time-based frame sampling (Phase 1 ingest)."""

import threading


class FrameSampler:
    """Uniform time-based sampler: at most one frame emitted per sample period.

    Raw WebRTC frames may arrive faster than the target rate (e.g. 30 FPS while
    the operator only wants 5 FPS in the rolling buffer). The sampler keeps the
    FIRST frame that arrives at-or-after each ``1 / target_fps`` boundary and
    decimates the rest, preserving the ORIGINAL capture timestamps so the
    downstream buffer can reconstruct true timing.

    The state machine is keyed off caller-supplied timestamps (float seconds)
    making it deterministic and unit-testable without a real clock.
    """

    def __init__(self, target_fps: float = 5.0) -> None:
        if target_fps <= 0:
            raise ValueError("target_fps must be > 0")
        self.target_fps = float(target_fps)
        self._period = 1.0 / target_fps
        self._last_emitted_ts: float | None = None
        self._lock = threading.Lock()
        self._sampled = 0
        self._decimated = 0

    @property
    def period(self) -> float:
        return self._period

    @property
    def sampled(self) -> int:
        return self._sampled

    @property
    def decimated(self) -> int:
        return self._decimated

    def accept(self, timestamp: float) -> bool:
        """Decide whether a frame arriving at ``timestamp`` should be emitted."""
        with self._lock:
            if self._last_emitted_ts is None:
                self._last_emitted_ts = timestamp
                self._sampled += 1
                return True
            elapsed = timestamp - self._last_emitted_ts
            if elapsed >= self._period:
                self._last_emitted_ts = timestamp
                self._sampled += 1
                return True
            # Clock jitter / out-of-order: always accept a frame that goes
            # backwards so the pipeline never stalls on a bad timestamp.
            if elapsed < 0:
                self._last_emitted_ts = timestamp
                self._sampled += 1
                return True
            self._decimated += 1
            return False

    def reset(self) -> None:
        with self._lock:
            self._last_emitted_ts = None
            self._sampled = 0
            self._decimated = 0