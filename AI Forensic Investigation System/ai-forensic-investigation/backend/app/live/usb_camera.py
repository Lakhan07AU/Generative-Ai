"""USB / DroidCam capture source for live sessions (Phase 9 transport).

``DROIDCAM_USB`` advertises that any local OpenCV-compatible capture device can
drive a live session: the same ingest pipeline the demo file transport uses.
DroidCam Desktop 4 exposes the phone's camera as a virtual "USB" device that
OpenCV opens with ``cv2.VideoCapture(device_index)`` (typically index 0).

The source behaves like :class:`~app.live.video_feeder.VideoFileFeeder` (a
daemon capture thread calling ``runtime.ingest_frame``) and additionally exposes
the :class:`~app.live.source.CameraSource` contract - ``connect``, ``read_frame``,
``is_alive`` and ``health`` - so live status screens can display source health.

Capture-device access is optional and off by default: the transport is only
exercised when a client explicitly requests ``transport == "droidcam_usb"``.
"""

import logging
import threading
import time
from typing import Optional

from app.core.config import settings
from app.live.source import CameraSource

logger = logging.getLogger(__name__)


class UsbCameraSource(CameraSource):
    """Daemon-thread camera capture source for the ``droidcam_usb`` transport."""

    name = "droidcam_usb"

    def __init__(
        self,
        runtime,
        device_index: Optional[int] = None,
        fps_target: Optional[float] = None,
        on_finished=None,
    ) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise ImportError(
                "OpenCV (cv2) is required for the droidcam_usb transport"
            ) from exc
        self._cv2 = cv2
        self._runtime = runtime
        self._device_index = int(
            device_index if device_index is not None else settings.DROIDCAM_DEVICE_INDEX
        )
        self._fps_target = fps_target
        self._stale_seconds = float(settings.DROIDCAM_STALE_SECONDS)
        self._max_restarts = int(settings.DROIDCAM_MAX_RESTARTS)
        self.on_finished = on_finished
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cap = None
        self._opened = False
        self._started_at = 0.0
        self._frames_read = 0
        self._dropped_frames = 0
        self._restarts = 0
        self._last_frame_at = 0.0
        self._health_error: Optional[str] = None

    # -- CameraSource contract ----------------------------------------------

    def connect(self) -> None:
        """Open the capture device. Raises if the device cannot be opened."""
        try:
            cap = self._cv2.VideoCapture(self._device_index)
            if cap is None or not cap.isOpened():
                cap.release() if cap is not None else None
                raise RuntimeError(
                    f"cannot open camera device index {self._device_index} "
                    f"(is the DroidCam driver installed?)"
                )
            native_fps = cap.get(self._cv2.CAP_PROP_FPS) or 0.0
            target = float(self._fps_target or settings.DROIDCAM_FPS or native_fps)
            if target > 0:
                cap.set(self._cv2.CAP_PROP_FPS, target)
        except Exception as exc:  # noqa: BLE001 - surface as health error
            self._opened = False
            self._health_error = str(exc)
            raise
        self._cap = cap
        self._opened = True
        self._health_error = None
        logger.info(
            "USB camera connected device_index=%s fps=%s",
            self._device_index,
            target,
        )

    def is_alive(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
            and (time.time() - self._last_frame_at) <= self._stale_seconds
        )

    def health(self) -> dict:
        return {
            "source": self.name,
            "device_index": self._device_index,
            "opened": self._opened,
            "alive": self.is_alive(),
            "running": self._thread is not None and self._thread.is_alive(),
            "frames_read": self._frames_read,
            "dropped_frames": self._dropped_frames,
            "restarts": self._restarts,
            "last_frame_at": self._last_frame_at,
            "now": time.time(),
            "error": self._health_error,
        }

    def read_frame(self):
        """Fetch the next frame from the open device (blocking read)."""
        if self._cap is None or not self._opened:
            self.connect()
        ok, frame = self._cap.read()
        if not ok:
            return None
        return frame

    # -- Thread management (mirrors VideoFileFeeder) -------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        if self._cap is None or not self._opened:
            self.connect()
        self._stop.clear()
        self._started_at = time.time()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"live-usb-{self._runtime.camera_id}",
        )
        self._thread.start()
        logger.info(
            "USB camera capture started camera=%s device_index=%s",
            self._runtime.camera_id,
            self._device_index,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            if self._thread is not threading.current_thread():
                self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None
        self._opened = False
        logger.info("USB camera capture stopped camera=%s", self._runtime.camera_id)

    def _reconnect(self) -> bool:
        if self._restarts >= self._max_restarts:
            logger.error(
                "USB camera camera=%s gave up after %s restarts",
                self._runtime.camera_id,
                self._restarts,
            )
            self._health_error = f"capture failed after {self._restarts} restarts"
            return False
        self._restarts += 1
        logger.warning(
            "USB camera camera=%s reconnect attempt %s",
            self._runtime.camera_id,
            self._restarts,
        )
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
        self._cap = None
        try:
            self.connect()
            return True
        except Exception as exc:  # noqa: BLE001
            self._health_error = str(exc)
            return False

    # -- Capture loop --------------------------------------------------------

    def _run(self) -> None:
        native_fps = 0.0
        if self._cap is not None:
            native_fps = self._cap.get(self._cv2.CAP_PROP_FPS) or 0.0
        target = float(self._fps_target or settings.DROIDCAM_FPS or native_fps) or 1.0
        period = 1.0 / max(target, 1.0)
        self._last_frame_at = time.time()
        consecutive_failures = 0
        try:
            while not self._stop.is_set():
                frame = self.read_frame()
                if frame is None:
                    consecutive_failures += 1
                    self._dropped_frames += 1
                    if consecutive_failures >= 10 and not self._reconnect():
                        if self.on_finished is not None:
                            self.on_finished()
                        break
                    self._stop.wait(period)
                    continue
                consecutive_failures = 0
                timestamp = time.time()
                self._runtime.ingest_frame(frame, timestamp)
                self._frames_read += 1
                self._last_frame_at = time.time()
                self._stop.wait(period)
        finally:
            logger.info("USB camera capture thread exited camera=%s", self._runtime.camera_id)


__all__ = ["UsbCameraSource"]