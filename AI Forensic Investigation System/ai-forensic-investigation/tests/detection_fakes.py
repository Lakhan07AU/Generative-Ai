"""Fake YOLO engine used by detection unit/integration tests."""

import threading
import time

import numpy as np

from app.detection.schemas import BoundingBox, DetectionFrame, DetectionObject


class FakeEngine:
    """Mimics ``DetectionEngine`` (concurrency-serialized infer) without YOLO.

    Callers register an ``on_infer(frame, kwargs)`` hook to control results, or
    pass a list of ``detections`` counts to return per call.
    """

    def __init__(self, detections_per_call=None, infer_ms: float = 0.0, on_infer=None):
        self._detections_per_call = list(detections_per_call or [])
        self._infer_ms = infer_ms
        self._on_infer = on_infer
        self._lock = threading.RLock()
        self.calls = 0
        self.last_args = None

    @property
    def class_names(self):
        return {0: "person", 1: "car"}

    def infer(self, frame, timestamp, session_id=None, frame_id=None, camera_id=None):
        with self._lock:
            self.calls += 1
            self.last_args = (frame, timestamp, session_id, frame_id, camera_id)
        if self._on_infer is not None:
            count = self._on_infer(frame, dict(
                timestamp=timestamp,
                session_id=session_id,
                frame_id=frame_id,
                camera_id=camera_id,
            ))
        else:
            count = 0
        if self._detections_per_call:
            count = self._detections_per_call.pop(0)
        time.sleep(self._infer_ms)
        h, w = (np.asarray(frame).shape[0], np.asarray(frame).shape[1]) if isinstance(frame, np.ndarray) and frame.ndim == 3 else (None, None)
        detections = []
        for i in range(count):
            detections.append(DetectionObject(
                detection_id=f"t-{frame_id or 'x'}-{i}",
                class_id=i,
                class_name=self.class_names.get(i, str(i)),
                confidence=0.9,
                bbox=BoundingBox(x1=10, y1=10 + i, x2=110, y2=110 + i),
                frame_timestamp=timestamp,
                session_id=session_id,
                frame_id=frame_id,
                camera_id=camera_id,
                frame_width=w,
                frame_height=h,
            ))
        return DetectionFrame(
            session_id=session_id,
            camera_id=camera_id,
            frame_id=frame_id,
            frame_timestamp=timestamp,
            frame_width=w,
            frame_height=h,
            detections=detections,
        )

    def close(self):
        return None


class FailingEngine(FakeEngine):
    """Raises on every inference; simulates model/device failure."""

    def infer(self, frame, timestamp, session_id=None, frame_id=None, camera_id=None):
        raise RuntimeError("simulated inference failure")