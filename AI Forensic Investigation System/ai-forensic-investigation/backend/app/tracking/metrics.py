"""Bounded, thread-safe per-session tracking metrics (Phase 3).

Discrete aggregate counters only - NO bboxes/centers/IDs/frames stored.
Latency = EMA/EMA-max of per-update latency_ms. Units documented.
"""

import threading
from datetime import datetime
from typing import Dict

from app.tracking.schemas import TrackingMetricsOut, utcnow


class TrackingMetrics:
    def __init__(self, max_tracks: int = 200, latency_window: float = 0.9) -> None:
        self._lock = threading.RLock()
        self._active_tracks = 0
        self._lost_tracks = 0
        self._removed_tracks = 0
        self._total_updates = 0
        self._total_events = 0
        self._events_by_type: Dict[str, int] = {}
        self._latency_avg_ms = 0.0
        self._latency_max_ms = 0.0
        self._latency_window = latency_window
        self._peak_concurrent = 0
        self._started_at = utcnow()
        self._max_tracks = max_tracks

    # ------------------------------------------------------------- recording
    def record_track_state(self, tracking_id: str, *, broadcast: bool = True, active: bool = True, latency_ms: float = 0.0) -> None:
        with self._lock:
            self._total_updates += 1
            if active:
                self._active_tracks += 1
                self._peak_concurrent = max(self._peak_concurrent, self._active_tracks)
            else:
                self._lost_tracks += 1
            if latency_ms > 0:
                self._latency_avg_ms = (
                    self._latency_window * self._latency_avg_ms
                    + (1 - self._latency_window) * latency_ms
                )
                self._latency_max_ms = max(self._latency_max_ms, latency_ms)

    # back-compat alias (detection-layer naming nuance)
    record_track_update = record_track_state

    def record_removed(self, tracking_id: str) -> None:
        with self._lock:
            self._removed_tracks += 1
            self._active_tracks = max(0, self._active_tracks - 1)

    def record_event(self, event_type: str) -> None:
        with self._lock:
            self._total_events += 1
            self._events_by_type[event_type] = self._events_by_type.get(event_type, 0) + 1

    # -------------------------------------------------------------- snapshot
    def snapshot(self) -> TrackingMetricsOut:
        with self._lock:
            return TrackingMetricsOut(
                active_tracks=self._active_tracks,
                active_updates=self._active_tracks,
                lost_tracks=self._lost_tracks,
                removed_tracks=self._removed_tracks,
                total_updates=self._total_updates,
                total_events=self._total_events,
                events_by_type=dict(self._events_by_type),
                latency_avg_ms=round(self._latency_avg_ms, 3),
                latency_max_ms=round(self._latency_max_ms, 3),
                peak_concurrent_tracks=self._peak_concurrent,
                started_at=self._started_at,
            )

    def reset(self) -> None:
        with self._lock:
            self._active_tracks = 0
            self._lost_tracks = 0
            self._removed_tracks = 0
            self._total_updates = 0
            self._total_events = 0
            self._events_by_type.clear()
            self._latency_avg_ms = 0.0
            self._latency_max_ms = 0.0
            self._peak_concurrent = 0
            self._started_at = utcnow()
