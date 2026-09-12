"""Track event detector - state-machine over TrackUpdate stream.

Visual-only semantic events: object_entered, object_exited, object_moved,
object_stopped, object_disappeared, prolonged_presence, object_reappeared.
Deterministic, thread-safe via RLock (feeds: tracking thread; reads: API/WS).
"""

import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.tracking.schemas import TrackState, TrackingEvent, TrackUpdate, utcnow

from app.tracking.motion import (
    CENTER_MAX_PX,
    STATIONARY_MIN_SECONDS,
    STATIONARY_MIN_FRAMES,
    REAPPEAR_MIN_HITS,
    PRESENCE_WINDOW_SECONDS,
)


class EventThresholds:
    def __init__(
        self,
        min_stationary_seconds: float = STATIONARY_MIN_SECONDS,
        prolonged_presence_seconds: float = 15.0,
        prolonged_lost_seconds: float = 5.0,
        reappeared_min_hits: int = REAPPEAR_MIN_HITS,
    ):
        self.min_stationary_seconds = min_stationary_seconds
        self.prolonged_presence_seconds = prolonged_presence_seconds
        self.prolonged_lost_seconds = prolonged_lost_seconds
        self.reappeared_min_hits = reappeared_min_hits


class TrackEventDetector:
    def __init__(self, thresholds: Optional[EventThresholds] = None):
        self.thresholds = thresholds or EventThresholds()
        self._lock = threading.RLock()
        self._last_state: Dict[str, TrackState] = {}
        self._entered_at: Dict[str, datetime] = {}
        self._stationary_at: Dict[str, Optional[datetime]] = {}
        self._moving_at: Dict[str, Optional[datetime]] = {}
        self._saw_lost_at: Dict[str, Optional[datetime]] = {}
        self._event_counts: Dict[str, int] = {}
        self._event_seq = 0
        self._total_events = 0

    def reset(self):
        with self._lock:
            self._last_state.clear()
            self._entered_at.clear()
            self._stationary_at.clear()
            self._moving_at.clear()
            self._saw_lost_at.clear()
            self._event_counts.clear()
            self._event_seq = 0
            self._total_events = 0

    def detect(self, update: TrackUpdate) -> List[TrackingEvent]:
        with self._lock:
            return self._detect_locked(update)

    def _detect_locked(self, update: TrackUpdate) -> List[TrackingEvent]:
        events = []
        tid = update.tracking_id
        state = update.state
        ts = update.frame_timestamp or utcnow()
        prev = self._last_state.get(tid)
        if prev is None:
            self._last_state[tid] = state
            self._entered_at[tid] = ts
            if state in (TrackState.NEW, TrackState.ACTIVE):
                events.append(self._event("object_entered", update, ts))
            return events

        if state in (TrackState.LOST, TrackState.REMOVED) and prev in (TrackState.NEW, TrackState.ACTIVE):
            if state == TrackState.LOST:
                self._saw_lost_at[tid] = ts
                events.append(self._event("object_disappeared", update, ts))
            else:
                events.append(self._event("object_exited", update, ts))
                self._last_state.pop(tid, None)
                self._entered_at.pop(tid, None)
                self._stationary_at.pop(tid, None)
                self._moving_at.pop(tid, None)
                self._saw_lost_at.pop(tid, None)
                return events

        if prev in (TrackState.LOST,) and state in (TrackState.NEW, TrackState.ACTIVE):
            lost_at = self._saw_lost_at.get(tid)
            if lost_at is not None and (ts - lost_at) >= timedelta(seconds=self.thresholds.prolonged_lost_seconds):
                events.append(self._event("object_reappeared", update, ts))
            self._saw_lost_at[tid] = None

        if state in (TrackState.NEW, TrackState.ACTIVE):
            stationary = bool(update.stationary_seconds is not None and update.stationary_seconds >= self.thresholds.min_stationary_seconds)
            if stationary and self._stationary_at.get(tid) is None:
                self._stationary_at[tid] = ts
                events.append(self._event("object_stopped", update, ts))
            if not stationary and self._stationary_at.get(tid) is not None:
                self._stationary_at[tid] = None
                events.append(self._event("object_moved", update, ts))
            if (ts - self._entered_at.get(tid, ts)) >= timedelta(seconds=self.thresholds.prolonged_presence_seconds):
                events.append(self._event("prolonged_presence", update, ts))

        self._last_state[tid] = state
        return events

    def _event(self, event_type, update, ts):
        self._event_seq += 1
        self._event_counts[event_type] = self._event_counts.get(event_type, 0) + 1
        self._total_events += 1
        return TrackingEvent(
            event_id=f"{event_type}-{self._event_seq:05d}",
            event_type=event_type,
            session_id=update.session_id, camera_id=update.camera_id,
            frame_index=update.frame_index, frame_timestamp=ts,
            tracking_id=update.tracking_id,
            metadata={"state": update.state.value, "label": update.label},
        )

    def event_counts(self):
        with self._lock:
            return dict(self._event_counts)

    def total_events(self):
        with self._lock:
            return self._total_events
