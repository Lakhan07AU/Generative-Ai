"""Video file frame feeder for live sessions (demo file transport).

Decodes frames from a real video file with OpenCV and feeds them into a live
session (ingestion -> sampler -> rolling buffer -> detection -> VLM ->
evidence) at the source video fps, or at an overriding ``fps_target``. Used
when ``LiveStartRequest.transport == "file"``.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)


class VideoFileFeeder:
    """Daemon thread decoding a video file into a live session."""

    def __init__(
        self,
        runtime,
        video_path: str,
        fps_target=None,
        loop: bool = False,
        on_finished=None,
    ) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise ImportError(
                "OpenCV (cv2) is required for the file transport"
            ) from exc
        self._cv2 = cv2
        self._runtime = runtime
        self._video_path = video_path
        self._fps_target = fps_target
        self._loop = loop
        self.on_finished = on_finished
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at = 0.0
        self._cap = cv2.VideoCapture(video_path)
        self._opened = self._cap.isOpened()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._started_at = time.time()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"live-file-{self._runtime.camera_id}",
        )
        self._thread.start()
        logger.info(
            "Video file feeder started camera=%s file=%s",
            self._runtime.camera_id,
            self._video_path,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            if self._thread is not threading.current_thread():
                self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Video file feeder stopped camera=%s", self._runtime.camera_id)

    def _run(self) -> None:
        if not self._opened:
            logger.error(
                "Failed to open video file camera=%s file=%s",
                self._runtime.camera_id,
                self._video_path,
            )
            if self.on_finished is not None:
                self.on_finished()
            return
        try:
            source_fps = self._cap.get(self._cv2.CAP_PROP_FPS) or 0.0
            period = 1.0 / (float(self._fps_target or source_fps) or 1.0)
            while not self._stop.is_set():
                ok, frame = self._cap.read()
                if not ok:
                    if self._loop:
                        self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    logger.info(
                        "Video file feeder reached EOF camera=%s",
                        self._runtime.camera_id,
                    )
                    if self.on_finished is not None:
                        self.on_finished()
                    break
                timestamp = time.time() - self._started_at
                self._runtime.ingest_frame(frame, timestamp)
                self._stop.wait(period)
        finally:
            self._cap.release()