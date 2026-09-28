"""In-memory real-time detection metrics (Phase 2).

Everything here is deliberately in-memory - no database rows per frame. State
is guarded by a lock so the ingestion thread (producer) and the inference
worker thread (consumer) can update it concurrently.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Optional


class _WindowRate:
    """Event rate measured over a sliding time window (events / elapsed).

    An exponential moving average of the instantaneous ``1/dt`` is unusable
    here: events arrive in bursts on separate threads, so consecutive samples
    can be microseconds apart and the average latches onto absurd values
    (this repo reported ~375,000 detections/sec on a 16 fps stream). A single
    shared "last timestamp" across several independent rates is worse still -
    each rate steals elapsed time from the others. Every rate therefore keeps
    its own bounded window of event timestamps.
    """

    def __init__(self, window_seconds: float, clock) -> None:
        self._clock = clock
        self._window = max(float(window_seconds), 0.1)
        self._stamps: Deque[float] = deque()

    def record(self, count: int = 1) -> None:
        if count <= 0:
            return
        now = self._clock()
        for _ in range(count):
            self._stamps.append(now)
        cutoff = now - self._window
        while self._stamps and self._stamps[0] < cutoff:
            self._stamps.popleft()

    def rate(self) -> float:
        if len(self._stamps) < 2:
            return 0.0
        span = self._stamps[-1] - self._stamps[0]
        if span <= 0:
            return 0.0
        return (len(self._stamps) - 1) / span


class DetectionMetrics:
    """Thread-safe counters + windowed rates."""

    def __init__(self, window_seconds: float = 5.0, clock=None) -> None:
        self._lock = threading.Lock()
        self._clock = clock or time.monotonic
        self._window = float(window_seconds)

        self._total_input = 0
        self._total_sampled = 0
        self._total_processed = 0
        self._total_detections = 0
        self._total_dropped = 0
        self._total_inference_errors = 0

        self._input_rate = _WindowRate(self._window, self._clock)
        self._sampled_rate = _WindowRate(self._window, self._clock)
        self._processed_rate = _WindowRate(self._window, self._clock)
        self._detection_rate = _WindowRate(self._window, self._clock)

        self._latency_sum_ms = 0.0
        self._latency_max_ms = 0.0
        self._latency_samples = 0

        self._queue_depth = 0
        self._last_frame_ts: Optional[float] = None

    # ---------------------------------------------------------------- events

    def record_input(self) -> None:
        with self._lock:
            self._total_input += 1
            self._input_rate.record()

    def record_sampled(self) -> None:
        with self._lock:
            self._total_sampled += 1
            self._sampled_rate.record()

    def record_processed(self, latency_ms: float) -> None:
        with self._lock:
            self._total_processed += 1
            self._processed_rate.record()
            self._latency_sum_ms += latency_ms
            self._latency_samples += 1
            if latency_ms > self._latency_max_ms:
                self._latency_max_ms = latency_ms

    def record_detections(self, count: int) -> None:
        with self._lock:
            self._total_detections += count
            self._detection_rate.record(count)

    def record_dropped(self) -> None:
        with self._lock:
            self._total_dropped += 1

    def record_inference_error(self) -> None:
        with self._lock:
            self._total_inference_errors += 1

    def set_queue_depth(self, depth: int) -> None:
        with self._lock:
            self._queue_depth = depth

    # --------------------------------------------------------------- snapshot

    def snapshot(self) -> dict:
        with self._lock:
            avg_latency_ms = (
                self._latency_sum_ms / self._latency_samples if self._latency_samples else 0.0
            )
            return {
                "total_input": self._total_input,
                "total_sampled": self._total_sampled,
                "total_processed": self._total_processed,
                "total_detections": self._total_detections,
                "total_dropped": self._total_dropped,
                "inference_errors": self._total_inference_errors,
                "input_fps": round(self._input_rate.rate(), 2),
                "sampled_fps": round(self._sampled_rate.rate(), 2),
                "processed_fps": round(self._processed_rate.rate(), 2),
                "detection_fps": round(self._detection_rate.rate(), 2),
                "inference_latency_avg_ms": round(avg_latency_ms, 2),
                "inference_latency_max_ms": round(self._latency_max_ms, 2),
                "queue_depth": self._queue_depth,
            }

    def reset(self) -> None:
        with self._lock:
            self.__init__(window_seconds=self._window, clock=self._clock)