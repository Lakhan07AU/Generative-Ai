"""Live camera source abstraction (Phase 1 ingest).

A :class:`LiveCameraSource` sits at the top of the pipeline::

    transport -> LiveCameraSource -> FrameIngestion -> FrameSampler
                                                        -> RollingFrameBuffer

Transports (WebRTC receiver, simulation feeder) call :meth:`push` whenever a
frame is ready; the source stamps it with a wall-clock timestamp and forwards
it to ingestion. If the underlying ingestion reports back-pressure (too many
frames) the frame is simply counted and dropped to protect the rolling buffer.
"""

import threading
import time


class LiveCameraSource:
    """Thread-safe adapter from a media transport into the ingest pipeline."""

    def __init__(self, ingestion=None, clock=None) -> None:
        if clock is None:
            clock = time.time
        self._ingestion = ingestion
        self._clock = clock
        self._lock = threading.Lock()
        self._pushed = 0
        self._dropped = 0

    @property
    def pushed(self) -> int:
        return self._pushed

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def ingestion(self):
        return self._ingestion

    def push(self, frame) -> bool:
        """Push a raw frame; stamped with the current wall-clock time."""
        return self.push_with_ts(frame, self._clock())

    def push_with_ts(self, frame, timestamp: float) -> bool:
        """Push a raw frame with an explicit timestamp (seconds)."""
        with self._lock:
            self._pushed += 1
        if self._ingestion is None:
            with self._lock:
                self._dropped += 1
            return False
        return self._ingestion.ingest(frame, timestamp)

    def bind(self, ingestion) -> None:
        self._ingestion = ingestion