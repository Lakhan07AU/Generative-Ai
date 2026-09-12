"""Per-session non-blocking inference worker (Phase 2).

The worker owns ONE camera session's detection queue + consumer thread. It is
independent per session so cameras never share queue state. Inference runs on a
dedicated daemon thread so FastAPI's event loop is never blocked by YOLO.

Backpressure policy (documented + tested):
  * The queue is bounded (``maxsize``).
  * When the queue is full the OLDEST queued frame is evicted and the NEWEST
    frame takes its place ("process newest, drop stale"). The worker prefers
    delivering the freshest detection state to the live UI.
  * Dropped frames are counted in :class:`DetectionMetrics`.
  * On stop, the worker may drain the queue (best effort) or discard it,
    controlled by ``drain``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Optional

from app.detection.metrics import DetectionMetrics
from app.detection.schemas import DetectionFrame

logger = logging.getLogger(__name__)

ResultCallback = Callable[[DetectionFrame], None]
ErrorCallback = Callable[[Exception], None]


@dataclass
class _PendingFrame:
    frame: object
    timestamp: float
    frame_id: Optional[int]
    session_id: Optional[int]
    camera_id: Optional[int]


class DetectionWorker:
    """One session's detection producer/consumer pair."""

    def __init__(
        self,
        engine,
        on_result: ResultCallback,
        on_error: Optional[ErrorCallback] = None,
        maxsize: int = 8,
        clock=None,
    ) -> None:
        self._engine = engine
        self._on_result = on_result or (lambda _frame: None)
        self._on_error = on_error or (lambda _exc: None)
        self._maxsize = max(1, int(maxsize))
        self._clock = clock or time.monotonic

        self._queue: Deque[_PendingFrame] = deque()
        self._lock = threading.Condition(threading.Lock())
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._metrics: Optional[DetectionMetrics] = None

    # -------------------------------------------------------------- control

    def start(self, metrics: DetectionMetrics) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._metrics = metrics
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="detection-worker",
            daemon=True,
        )
        self._thread.start()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def queue_maxsize(self) -> int:
        return self._maxsize

    def submit(
        self,
        frame,
        timestamp: float,
        frame_id: Optional[int] = None,
        session_id: Optional[int] = None,
        camera_id: Optional[int] = None,
    ) -> bool:
        """Queue a sampled frame for inference.

        Returns True when the frame was accepted (possibly evicting the oldest
        queued frame) and False when the worker is not running.
        """
        if not self.running:
            return False
        pending = _PendingFrame(
            frame=frame,
            timestamp=timestamp,
            frame_id=frame_id,
            session_id=session_id,
            camera_id=camera_id,
        )
        evicted = 0
        with self._lock:
            if len(self._queue) >= self._maxsize:
                self._queue.popleft()  # drop oldest (stale) frame
                evicted = 1
            self._queue.append(pending)
            self._lock.notify()
        if self._metrics is not None:
            self._metrics.set_queue_depth(len(self._queue))
            if evicted:
                self._metrics.record_dropped()
        return True

    def stop(self, drain: bool = False, timeout: float = 5.0) -> None:
        """Signal the worker to finish and join the thread.

        When ``drain`` is True the worker keeps consuming until the queue is
        empty; otherwise remaining frames are discarded. Never blocks the
        caller for more than ``timeout`` seconds (daemon thread otherwise).
        """
        self._stop.set()
        with self._lock:
            if not drain:
                self._queue.clear()
            self._lock.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def reset(self) -> None:
        """Discard queued frames without stopping the worker."""
        with self._lock:
            self._queue.clear()
            self._lock.notify()

    # ----------------------------------------------------------------- run

    def _run(self) -> None:
        while not self._stop.is_set():
            pending: Optional[_PendingFrame] = None
            with self._lock:
                while not self._queue and not self._stop.is_set():
                    self._lock.wait(timeout=0.25)
                if self._queue:
                    pending = self._queue.popleft()
                    if self._metrics is not None:
                        self._metrics.set_queue_depth(len(self._queue))
            if pending is None:
                continue
            self._process(pending)
        # drain mode: consume whatever is left after stop signal
        while self._queue:
            with self._lock:
                pending = self._queue.popleft() if self._queue else None
                if self._metrics is not None:
                    self._metrics.set_queue_depth(len(self._queue))
            if pending is None:
                break
            self._process(pending)

    def _process(self, pending: _PendingFrame) -> None:
        started = self._clock()
        try:
            frame = self._engine.infer(
                pending.frame,
                timestamp=pending.timestamp,
                session_id=pending.session_id,
                frame_id=pending.frame_id,
                camera_id=pending.camera_id,
            )
        except Exception as exc:  # noqa: BLE001 - one failure must not kill the worker
            if self._metrics is not None:
                self._metrics.record_inference_error()
            logger.warning(
                "Detection inference error camera=%s frame=%s: %s",
                pending.camera_id,
                pending.frame_id,
                exc,
            )
            self._on_error(exc)
            return
        elapsed_ms = (self._clock() - started) * 1000.0
        if self._metrics is not None:
            self._metrics.record_processed(latency_ms=elapsed_ms)
            self._metrics.record_detections(len(frame.detections))
        self._on_result(frame)