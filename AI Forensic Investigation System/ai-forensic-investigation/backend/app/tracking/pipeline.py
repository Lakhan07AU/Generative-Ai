"""Phase 3 tracking pipeline (per-session, per-camera; bounded, thread-safe)."""

import threading
from datetime import datetime
from typing import Callable, List, Optional

from app.tracking.event_detector import TrackEventDetector, EventThresholds
from app.tracking.metrics import TrackingMetrics
from app.tracking.schemas import TrackState, TrackSummary, TrackUpdate, utcnow
from app.tracking.tracker import IoUMultiObjectTracker


class TrackingPipeline:
    """One per (session_id, camera_id). Visual IDs only; ABS pPx metrics.

    Bounded: max_tracks, bounded histograms, aggregate-only metrics snapshot
    (no bboxes/centers/IDs in the broadcast). Thread-safe:
    detection-thread write (update), API-thread read (snapshot).
    """

    def __init__(
        self,
        session_id: str = "",
        camera_id: str = "",
        iou_threshold: float = 0.3,
        max_missing: int = 30,
        max_tracks: int = 200,
        on_track: Optional[Callable] = None,
        on_event: Optional[Callable] = None,
    ) -> None:
        self.session_id = session_id
        self.camera_id = camera_id
        self._lock = threading.RLock()
        self._tracker = IoUMultiObjectTracker(
            iou_threshold=iou_threshold, max_missing=max_missing, max_tracks=max_tracks
        )
        self._detector = TrackEventDetector(thresholds=EventThresholds())
        self._metrics = TrackingMetrics(max_tracks=max_tracks)
        self._on_track_cb = on_track
        self._on_event_cb = on_event
        self._stopped = False

    def update(self, detections, frame_index, ts=None) -> List[TrackUpdate]:
        ts = ts or utcnow()
        with self._lock:
            if self._stopped:
                return []
            updates = self._tracker.update(detections, frame_index, ts)
            for u in updates:
                self._metrics.record_track_state(
                    u.tracking_id, active=(u.state in (TrackState.NEW, TrackState.ACTIVE)),
                    latency_ms=u.processing_latency_ms if hasattr(u, "processing_latency_ms") else 0.0,
                )
                for ev in self._detector.detect(u):
                    self._metrics.record_event(ev.event_type)
                    if self._on_event_cb:
                        self._on_event_cb(ev)
                if self._on_track_cb:
                    self._on_track_cb(u)
            return updates

    def snapshot(self) -> dict:
        snap = self._metrics.snapshot().as_broadcast()
        # "active_tracks" must be the LIVE count of currently tracked objects,
        # not the cumulative active-state update counter. Derive it from the
        # tracker so aggregate metrics stay ID-free.
        live_active = sum(
            1 for t in self._tracker.tracks() if t.state in (TrackState.NEW, TrackState.ACTIVE)
        )
        snap["active_tracks"] = live_active
        snap["session_id"] = self.session_id
        snap["camera_id"] = self.camera_id
        return snap

    def tracks(self) -> List[TrackSummary]:
        return self._tracker.tracks()

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            self._tracker.remove_all()
            self._metrics.reset()

    def reset(self) -> None:
        with self._lock:
            self._tracker.remove_all()
            self._detector.reset()
            self._metrics.reset()
            self._stopped = False
