"""Per-session detection pipeline (Phase 2).

A :class:`DetectionPipeline` is created for each live session. It holds the
session's own metrics, its own bounded worker, and a recent-result history so
sessions are fully isolated (Camera A's detections never reach Camera B).

The underlying model (engine) may be shared across sessions via
:func:`app.detection.engine.get_engine` - sharing is concurrency-safe because
the engine serializes inference with a lock - but queues, workers, metrics, and
recent results are always per-session.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Deque, List, Optional

from app.core.config import settings
from app.detection.engine import DetectionEngine, get_engine
from app.detection.metrics import DetectionMetrics
from app.detection.schemas import DetectionFrame
from app.detection.worker import DetectionWorker

logger = logging.getLogger(__name__)


class DetectionPipeline:
    """Owns a session's inference worker, metrics, and recent results."""

    def __init__(
        self,
        engine: DetectionEngine,
        on_result,
        on_error=None,
        queue_size: Optional[int] = None,
        recent_frames: Optional[int] = None,
        clock=None,
    ) -> None:
        self.engine = engine
        self.on_result = on_result or (lambda _frame: None)
        self.on_error = on_error or (lambda _exc: None)
        self.queue_size = int(queue_size or settings.DETECTION_QUEUE_SIZE)
        self.recent_frames = int(recent_frames or settings.DETECTION_RECENT_FRAMES)

        self.metrics = DetectionMetrics(clock=clock)
        self.worker = DetectionWorker(
            engine=engine,
            on_result=self._handle_result,
            on_error=self.on_error,
            maxsize=self.queue_size,
            clock=clock,
        )
        self._recent: Deque[dict] = deque(maxlen=self.recent_frames)
        self._lock = threading.Lock()
        self._started = False

    # -------------------------------------------------------------- public

    def start(self) -> None:
        if self._started:
            return
        self.worker.start(self.metrics)
        self._started = True

    @property
    def running(self) -> bool:
        return self.worker.running

    def submit(self, frame, timestamp: float, frame_id=None, session_id=None, camera_id=None) -> bool:
        return self.worker.submit(
            frame=frame,
            timestamp=timestamp,
            frame_id=frame_id,
            session_id=session_id,
            camera_id=camera_id,
        )

    def stop(self, drain: bool = False, timeout: float = 5.0) -> None:
        """:returns: nothing; frees the worker thread."""
        self.worker.stop(drain=drain, timeout=timeout)
        self._started = False

    def recent_results(self, limit: Optional[int] = None) -> List[dict]:
        with self._lock:
            items = list(self._recent)
        if limit is not None and len(items) > limit:
            items = items[-limit:]
        return items

    def snapshot(self) -> dict:
        return self.metrics.snapshot()

    # --------------------------------------------------------------- intern

    def _handle_result(self, frame: DetectionFrame) -> None:
        broadcast = frame.as_broadcast()
        with self._lock:
            self._recent.append(broadcast)
        self.on_result(frame)

    @classmethod
    def build(
        cls,
        on_result,
        on_error=None,
        queue_size: Optional[int] = None,
        recent_frames: Optional[int] = None,
        clock=None,
    ) -> "DetectionPipeline":
        """Build a pipeline sharing the configured engine (registry)."""
        engine = get_engine()
        return cls(
            engine=engine,
            on_result=on_result,
            on_error=on_error,
            queue_size=queue_size,
            recent_frames=recent_frames,
            clock=clock,
        )


def detection_enabled() -> bool:
    return bool(settings.YOLO_DETECTION_ENABLED)