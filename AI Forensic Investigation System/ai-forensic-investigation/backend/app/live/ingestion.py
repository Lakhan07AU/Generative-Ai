"""Frame ingestion orchestrator (Phase 1 ingest).

Deliberately decoupled from any computer-vision model: YOLO and downstream
analysis run later on snapshots taken from the rolling buffer, never inside the
ingestion hot path.
"""

import threading
from typing import Callable, Optional


class FrameIngestion:
    """Routes raw frames from a :class:`LiveCameraSource` through the sampler
    into the rolling buffer.

    Responsibilities:
      * bound memory: reject oversized frames (``max_frame_bytes``);
      * bound rate: cap accepted source frames/seconds (``source_fps_cap``);
      * decimate: let the :class:`FrameSampler` pick frames for the buffer.

    Optional callbacks keep the pipeline decoupled from downstream consumers:
      * ``on_input(frame, timestamp)`` - every accepted source frame;
      * ``on_sampled(frame, timestamp, frame_id)`` - frames that entered the
        rolling buffer. Phase 2 feeds these into YOLO detection.

    ``ingest()`` returns ``True`` when the frame was sampled into the buffer
    and ``False`` when it was decimated or rejected.
    """

    def __init__(
        self,
        sampler,
        buffer,
        source_fps_cap: float = 30.0,
        max_frame_bytes: int = 4 * 1024 * 1024,
        on_input: Optional[Callable[[object, float], None]] = None,
        on_sampled: Optional[Callable[[object, float, int], None]] = None,
    ) -> None:
        self.sampler = sampler
        self.buffer = buffer
        if source_fps_cap <= 0:
            raise ValueError("source_fps_cap must be > 0")
        if max_frame_bytes <= 0:
            raise ValueError("max_frame_bytes must be > 0")
        self._source_fps_cap = float(source_fps_cap)
        self._max_frame_bytes = int(max_frame_bytes)
        self._min_source_interval = 1.0 / source_fps_cap
        self._lock = threading.Lock()
        self._last_source_ts: float | None = None
        self._received = 0
        self._rejected = 0
        self._decimated = 0
        self._sampled = 0
        self._on_input = on_input
        self._on_sampled = on_sampled

    # -------------------------------------------------------------- stats

    @property
    def received(self) -> int:
        return self._received

    @property
    def rejected(self) -> int:
        return self._rejected

    @property
    def decimated(self) -> int:
        return self._decimated

    @property
    def sampled(self) -> int:
        return self._sampled

    # --------------------------------------------------------------- main

    @staticmethod
    def frame_size(frame) -> int:
        if hasattr(frame, "nbytes"):
            return int(frame.nbytes)
        if hasattr(frame, "__len__"):
            try:
                return int(len(frame))
            except (TypeError, ValueError):
                return 0
        return 0

    def ingest(self, frame, timestamp: float) -> bool:
        """Ingest a single raw frame arriving at ``timestamp`` (seconds)."""
        with self._lock:
            self._received += 1
            if self.frame_size(frame) > self._max_frame_bytes:
                self._rejected += 1
                return False
            if (
                self._last_source_ts is not None
                and timestamp - self._last_source_ts >= 0
                and timestamp - self._last_source_ts < self._min_source_interval
            ):
                self._rejected += 1
                return False
            self._last_source_ts = timestamp
        if self._on_input is not None:
            self._on_input(frame, timestamp)
        if self.sampler.accept(timestamp):
            self.buffer.append(frame, timestamp)
            with self._lock:
                self._sampled += 1
                frame_id = self._sampled
            if self._on_sampled is not None:
                self._on_sampled(frame, timestamp, frame_id)
            return True
        with self._lock:
            self._decimated += 1
        return False