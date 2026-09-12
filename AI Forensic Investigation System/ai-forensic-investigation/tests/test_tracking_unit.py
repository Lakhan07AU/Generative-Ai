"""Phase 3 unit tests: motion, tracker, event detector, metrics, pipeline.

All runs are local/synthetic (numpy-only, no camera, no YOLO, no network).
Real-device / real-camera coverage is intentionally NOT part of this suite.
"""

import importlib
from datetime import datetime, timezone

import pytest

from app.tracking.schemas import TrackState, TrackingEvent, TrackUpdate, utcnow
from app.tracking.motion import (
    CENTER_MAX_PX,
    center_of_bbox,
    displacement_px,
    pixel_velocity_px_per_frame,
    path_distance_px,
    stationary_seconds,
    moving_seconds,
    stationary_ratio,
)
from app.tracking.tracker import IoUMultiObjectTracker
from app.tracking.metrics import TrackingMetrics
from app.tracking.pipeline import TrackingPipeline
from app.tracking.event_detector import TrackEventDetector, EventThresholds


def _det(center_x, center_y, w=20, h=40, score=0.85, i=0):
    x1 = center_x - w // 2
    return {"bbox": [x1, center_y - h // 2, x1 + w, center_y + h // 2],
            "score": score, "class_id": i, "label": "Person"}


class TestMotion:
    def test_center(self):
        assert center_of_bbox([10, 20, 30, 40]) == [20.0, 30.0]

    def test_displacement_and_direction(self):
        d = displacement_px([0, 0], [3, 4])
        assert d == pytest.approx(5.0)

    def test_constants_are_absolute_px(self):
        assert CENTER_MAX_PX == 8.0

    def test_path_distance_cumulative(self):
        c = [[0, 0], [3, 4], [3, 4]]
        assert path_distance_px(c) == pytest.approx(5.0)

    def test_stationary_motion_seconds(self):
        s = stationary_seconds([[0, 0], [1, 1], [2, 2]], stationary_tolerance_px=4.0, fps=5.0)
        assert s == pytest.approx(0.4)
        m = moving_seconds([[0, 0], [3, 3]], stationary_tolerance_px=4.0, fps=5.0)
        assert m == pytest.approx(0.2)


class TestTrackerLifecycle:
    def test_new_creates_track(self):
        tr = IoUMultiObjectTracker(iou_threshold=0.3, max_missing=30, max_tracks=10)
        ups = tr.update([_det(100, 100)], 0, utcnow())
        assert len(ups) == 1
        assert ups[0].state == TrackState.NEW
        assert ups[0].tracking_id == "Person-000001"

    def test_match_persists_id(self):
        tr = IoUMultiObjectTracker(iou_threshold=0.3, max_missing=30, max_tracks=10)
        first = tr.update([_det(100, 100)], 0, utcnow())[0]
        second = tr.update([_det(101, 100)], 1, utcnow())[0]
        assert second.tracking_id == first.tracking_id
        assert second.state == TrackState.ACTIVE

    def test_lost_then_removed(self):
        tr = IoUMultiObjectTracker(iou_threshold=0.3, max_missing=2, max_tracks=10)
        tr.update([_det(100, 100)], 0, utcnow())
        for i in range(3):
            tr.update([], i + 1, utcnow())
        assert len(tr.tracks()) == 0


class TestEventDetector:
    def test_detect_returns_events(self):
        d = TrackEventDetector(thresholds=EventThresholds())
        u = TrackUpdate(
            session_id="s1", camera_id="cam1", frame_index=0,
            frame_timestamp=utcnow(), tracking_id="Person-1",
            state=TrackState.NEW, label="Person",
        )
        evs = d.detect(u)
        assert isinstance(evs, list)


class TestMetrics:
    def test_snapshot_fields(self):
        m = TrackingMetrics()
        m.record_track_state("Person-1", active=True, latency_ms=4.2)
        m.record_event("object_entered")
        snap = m.snapshot().as_broadcast()
        assert snap["type"] == "tracking_metrics"
        assert snap["total_updates"] == 1
        assert snap["total_events"] == 1


class TestPipeline:
    def test_update_and_snapshot(self):
        p = TrackingPipeline(session_id="s", camera_id="cam")
        ups = p.update([_det(100, 100)], 0, utcnow())
        assert len(ups) == 1
        snap = p.snapshot()
        assert "active_tracks" in snap

    def test_stop_releases(self):
        p = TrackingPipeline(session_id="s", camera_id="cam")
        p.update([_det(100, 100)], 0, utcnow())
        p.stop()
        assert p.snapshot()["active_tracks"] == 0
