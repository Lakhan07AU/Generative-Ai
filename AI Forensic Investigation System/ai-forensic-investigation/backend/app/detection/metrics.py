"""In-memory real-time detection metrics (Phase 2).

Everything here is deliberately in-memory - no database rows per frame. State
is guarded by a lock so the ingestion thread (producer) and the inference
worker thread (consumer) can update it concurrently.
"""

from __future__ import annotations

import threading
import time
from typing import Optional


class DetectionMetrics:
    """Thread-safe counters + exponential moving average rates."""

    def __init__(self, window_seconds: float = 5.0, clock=None) -> None:
        self._lock = threading.Lock()
        self._clock = clock or time.monotonic
        self._window = float(window_seconds)
        self._alpha = 2.0 / (float(window_seconds) + 1.0)

        self._total_input = 0
        self._total_sampled = 0
        self._total_processed = 0
        self._total_detections = 0
        self._total_dropped = 0
        self._total_inference_errors = 0

        self._input_fps = 0.0
        self._sampled_fps = 0.0
        self._processed_fps = 0.0
        self._detection_fps = 0.0

        self._latency_sum_ms = 0.0
        self._latency_max_ms = 0.0
        self._latency_samples = 0

        self._queue_depth = 0
        self._last_frame_ts: Optional[float] = None

    # ---------------------------------------------------------------- events

    def record_input(self) -> None:
        with self._lock:
            self._total_input += 1
            self._input_fps = self._rate(self._input_fps, self._total_input)

    def record_sampled(self) -> None:
        with self._lock:
            self._total_sampled += 1
            self._sampled_fps = self._rate(self._sampled_fps, self._total_sampled)

    def record_processed(self, latency_ms: float) -> None:
        with self._lock:
            self._total_processed += 1
            self._processed_fps = self._rate(self._processed_fps, self._total_processed)
            self._latency_sum_ms += latency_ms
            self._latency_samples += 1
            if latency_ms > self._latency_max_ms:
                self._latency_max_ms = latency_ms

    def record_detections(self, count: int) -> None:
        with self._lock:
            self._total_detections += count
            self._detection_fps = self._rate(self._detection_fps, self._total_detections)

    def record_dropped(self) -> None:
        with self._lock:
            self._total_dropped += 1

    def record_inference_error(self) -> None:
        with self._lock:
            self._total_inference_errors += 1

    def set_queue_depth(self, depth: int) -> None:
        with self._lock:
            self._queue_depth = depth

    # ------------------------------------------------------------------ rates

    def _rate(self, current_ema: float, total: int) -> float:
        now = self._clock()
        if self._last_frame_ts is None:
            self._last_frame_ts = now
            return 0.0
        dt = now - self._last_frame_ts
        if dt <= 0:
            return current_ema
        self._last_frame_ts = now
        instant = 1.0 / dt
        return current_ema + self._alpha * (instant - current_ema)

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
                "input_fps": round(self._input_fps, 2),
                "sampled_fps": round(self._sampled_fps, 2),
                "processed_fps": round(self._processed_fps, 2),
                "detection_fps": round(self._detection_fps, 2),
                "inference_latency_avg_ms": round(avg_latency_ms, 2),
                "inference_latency_max_ms": round(self._latency_max_ms, 2),
                "queue_depth": self._queue_depth,
            }

    def reset(self) -> None:
        with self._lock:
            self.__init__(window_seconds=self._window, clock=self._clock)