"""Synthetic frame feeder for live sessions (Phase 1 dev/demo transport).

Feeds deterministic BGR frames into a session at ``2x fps_target`` so the
pipeline (ingestion -> sampler -> rolling buffer) can be exercised without a
physical camera. Used when ``LiveStartRequest.transport == "simulation"``.
"""

import threading
import time

import numpy as np


class FrameSimulationFeeder:
    """Daemon thread producing synthetic frames for a live session."""

    FRAME_SIZE = 96  # 96x96 BGR frames keep the demo light

    def __init__(self, runtime) -> None:
        self._runtime = runtime
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._counter = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._counter = 0
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"live-sim-{self._runtime.camera_id}",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        period = 1.0 / max(self._runtime.fps_target * 2.0, 1.0)
        while not self._stop.is_set():
            self._counter += 1
            frame = self._make_frame(self._counter)
            self._runtime.ingest_frame(frame, time.time())
            self._stop.wait(period)

    @staticmethod
    def _make_frame(counter: int) -> np.ndarray:
        size = FrameSimulationFeeder.FRAME_SIZE
        frame = np.zeros((size, size, 3), dtype=np.uint8)
        # Moving vertical bar that shifts each frame for visual feedback.
        x = (counter * 4) % size
        frame[:, x : x + 8, 0] = 255
        frame[:, x : x + 8, 1] = 128 + (counter % 64)
        frame[::16, :] = 64
        return frame