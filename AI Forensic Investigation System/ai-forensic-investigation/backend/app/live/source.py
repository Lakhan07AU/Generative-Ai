"""Live camera source abstraction (Phase 1 ingest).

A :class:`LiveCameraSource` sits at the top of the pipeline::

    transport -> LiveCameraSource -> FrameIngestion -> FrameSampler
                                                        -> RollingFrameBuffer

Push transports (WebRTC receiver, simulation feeder) call :meth:`push` whenever
a frame is ready; pull transports (USB / DroidCam, demo video files) run their
own capture thread and call :meth:`push_with_ts`. The source stamps frames with
a wall-clock timestamp and forwards them to ingestion. If the underlying
ingestion reports back-pressure (too many frames) the frame is counted and
dropped to protect the rolling buffer.

:class:`CameraSource` is the base contract every media transport satisfies so
status and health endpoints can treat all sources uniformly.
"""

import threading
import time
from typing import Optional


class CameraSource:
    """Base contract for a media transport delivering frames into a session.

    Push transports deliver frames through a bound :class:`LiveCameraSource`;
    pull transports own a capture thread and expose the optional fetch API.
    """

    name: str = "base"

    def connect(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        pass

    def is_alive(self) -> bool:
        return False

    def health(self) -> dict:
        return {"source": self.name, "alive": self.is_alive()}

    def read_frame(self):
        """Fetch the next raw frame (pull sources only)."""
        raise NotImplementedError


class LiveCameraSource(CameraSource):
    """Thread-safe adapter from a media transport into the ingest pipeline."""

    name = "push"

    def __init__(self, ingestion=None, clock=None) -> None:
        if clock is None:
            clock = time.time
        self._ingestion = ingestion
        self._clock = clock
        self._lock = threading.Lock()
        self._pushed = 0
        self._dropped = 0
        self._connected_at: Optional[float] = None
        self._last_frame_at: Optional[float] = None

    @property
    def pushed(self) -> int:
        return self._pushed

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def ingestion(self):
        return self._ingestion

    @property
    def connected_at(self) -> Optional[float]:
        return self._connected_at

    @property
    def last_frame_at(self) -> Optional[float]:
        return self._last_frame_at

    def connect(self) -> None:
        self._connected_at = self._clock()

    def disconnect(self) -> None:
        self._connected_at = None
        self._last_frame_at = None

    def is_alive(self) -> bool:
        last = self._last_frame_at
        return last is not None and (self._clock() - last) < 5.0

    def health(self) -> dict:
        last = self._last_frame_at
        return {
            "source": self.name,
            "alive": self.is_alive(),
            "pushed": self._pushed,
            "dropped": self._dropped,
            "connected_at": self._connected_at,
            "last_frame_at": last,
            "now": self._clock(),
        }

    def push(self, frame) -> bool:
        """Push a raw frame; stamped with the current wall-clock time."""
        return self.push_with_ts(frame, self._clock())

    def push_with_ts(self, frame, timestamp: float) -> bool:
        """Push a raw frame with an explicit timestamp (seconds)."""
        with self._lock:
            self._pushed += 1
            self._last_frame_at = timestamp
        if self._ingestion is None:
            with self._lock:
                self._dropped += 1
            return False
        return self._ingestion.ingest(frame, timestamp)

    def bind(self, ingestion) -> None:
        self._ingestion = ingestion


__all__ = ["CameraSource", "LiveCameraSource"]