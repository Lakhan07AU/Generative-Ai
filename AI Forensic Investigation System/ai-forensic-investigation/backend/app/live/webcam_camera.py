"""Laptop webcam capture source for live sessions (transport ``webcam``).

``webcam`` and ``droidcam_usb`` share ONE implementation - there is no second
capture pipeline in the codebase::

    webcam            droidcam_usb
       \\               /
        LocalOpenCVCameraSource        (app/live/webcam_camera.py)
                    |
                    v
          runtime.ingest_frame(frame, ts)
                    |
          FrameIngestion -> FrameSampler -> RollingFrameBuffer -> YOLO -> tracking

Both transports open a local OpenCV-compatible capture device with
``cv2.VideoCapture(device_index)`` and push frames into exactly the same ingest
path the demo file transport uses, so a laptop webcam, a USB capture card and a
DroidCam virtual camera all share identical sampling, detection, tracking,
evidence and audit behaviour.

The source also satisfies the full :class:`~app.live.source.CameraSource`
contract - ``connect``, ``disconnect``, ``read_frame``, ``start``, ``stop``,
``is_alive`` and ``health`` - so live status screens can display source health
uniformly for every transport.

Capture-device access is optional and off by default: a device is only ever
opened when a client explicitly requests ``transport == "webcam"`` (or
``"droidcam_usb"``), or when a verification script calls this class directly.
Device index 0 is a default, not a guarantee - probing is left to the
verification script so a missing device fails loudly instead of silently
producing zero frames.
"""

import logging
import threading
import time
from typing import Optional

from app.core.config import settings
from app.live.source import CameraSource

logger = logging.getLogger(__name__)


class LocalOpenCVCameraSource(CameraSource):
    """Daemon-thread OpenCV capture source for local capture devices.

    Subclasses only supply a transport name and the settings prefix they read
    their defaults from (``WEBCAM_`` or ``DROIDCAM_``).
    """

    name = "local_opencv"
    settings_prefix = "WEBCAM"

    def __init__(
        self,
        runtime,
        device_index: Optional[int] = None,
        fps_target: Optional[float] = None,
        on_finished=None,
        settings_prefix: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise ImportError(
                "OpenCV (cv2) is required for the webcam/droidcam_usb transport"
            ) from exc
        self._cv2 = cv2
        self._runtime = runtime
        self._prefix = (settings_prefix or self.settings_prefix).upper()
        if name is not None:
            self.name = name

        def _setting(suffix: str, default):
            value = getattr(settings, f"{self._prefix}_{suffix}", None)
            return default if value is None else value

        self._device_index = int(
            device_index if device_index is not None else _setting("DEVICE_INDEX", 0)
        )
        self._fps_target = fps_target
        self._prefix_fps = float(_setting("FPS", 0.0) or 0.0)
        self._width = int(_setting("WIDTH", 640) or 0)
        self._height = int(_setting("HEIGHT", 480) or 0)
        self._stale_seconds = float(_setting("STALE_SECONDS", 5.0))
        self._max_restarts = int(_setting("MAX_RESTARTS", 3))
        self._max_consecutive_failures = int(_setting("MAX_CONSECUTIVE_FAILURES", 10))
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
        """Open the capture device. Raises if the device cannot be opened.

        ``cv2.VideoCapture(index)`` frequently returns an object that reports
        ``isOpened() == True`` for a non-existent device until the first
        ``read()`` fails, so a real frame read is attempted before the device is
        declared open. This prevents claiming a working webcam that does not
        exist.
        """
        try:
            cap = self._cv2.VideoCapture(self._device_index)
            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                raise RuntimeError(
                    f"cannot open camera device index {self._device_index} "
                    f"(no such capture device, or it is in use by another application)"
                )
            native_fps = cap.get(self._cv2.CAP_PROP_FPS) or 0.0
            target = float(self._fps_target or self._prefix_fps or native_fps or 0.0)
            if target > 0:
                cap.set(self._cv2.CAP_PROP_FPS, target)
            if self._width > 0:
                cap.set(self._cv2.CAP_PROP_FRAME_WIDTH, float(self._width))
            if self._height > 0:
                cap.set(self._cv2.CAP_PROP_FRAME_HEIGHT, float(self._height))
            # Confirm the device really produces pixels before reporting open.
            ok, frame = cap.read()
            if not ok or frame is None or getattr(frame, "size", 0) == 0:
                cap.release()
                raise RuntimeError(
                    f"camera device index {self._device_index} opened but returned no frame"
                )
            self._native_fps = native_fps
            self._effective_fps = target
        except Exception as exc:  # noqa: BLE001 - surface as health error
            self._opened = False
            self._health_error = str(exc)
            raise
        self._cap = cap
        self._opened = True
        self._health_error = None
        self._last_frame_at = time.time()
        logger.info(
            "%s camera connected device_index=%s fps=%s",
            self.name,
            self._device_index,
            self._effective_fps,
        )

    def disconnect(self) -> None:
        """Release the capture device (idempotent)."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None
        self._opened = False

    def is_alive(self) -> bool:
        if self._thread is None or not self._thread.is_alive():
            return False
        if self._last_frame_at <= 0:
            return False
        return (time.time() - self._last_frame_at) <= self._stale_seconds

    def health(self) -> dict:
        return {
            "source": self.name,
            "device_index": self._device_index,
            "opened": self._opened,
            "alive": self.is_alive(),
            "running": self.running,
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
        if not ok or frame is None:
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
            name=f"live-{self.name}-{self._runtime.camera_id}",
        )
        self._thread.start()
        logger.info(
            "%s camera capture started camera=%s device_index=%s",
            self.name,
            self._runtime.camera_id,
            self._device_index,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            if self._thread is not threading.current_thread():
                self._thread.join(timeout=2.0)
            self._thread = None
        self.disconnect()
        logger.info("%s camera capture stopped camera=%s", self.name, self._runtime.camera_id)

    def _reconnect(self) -> bool:
        """Bounded reconnect. Never loops forever: gives up after max_restarts."""
        if self._restarts >= self._max_restarts:
            logger.error(
                "%s camera camera=%s gave up after %s restarts",
                self.name,
                self._runtime.camera_id,
                self._restarts,
            )
            self._health_error = f"capture failed after {self._restarts} restarts"
            return False
        self._restarts += 1
        logger.warning(
            "%s camera camera=%s reconnect attempt %s/%s",
            self.name,
            self._runtime.camera_id,
            self._restarts,
            self._max_restarts,
        )
        self.disconnect()
        try:
            self.connect()
            return True
        except Exception as exc:  # noqa: BLE001
            self._health_error = str(exc)
            return False

    # -- Capture loop --------------------------------------------------------

    def _run(self) -> None:
        target = float(self._fps_target or getattr(self, "_effective_fps", 0.0) or 10.0) or 10.0
        period = 1.0 / max(target, 1.0)
        self._last_frame_at = time.time()
        consecutive_failures = 0
        try:
            while not self._stop.is_set():
                try:
                    frame = self.read_frame()
                except Exception as exc:  # noqa: BLE001 - device died mid-stream
                    self._health_error = str(exc)
                    frame = None
                if frame is None:
                    consecutive_failures += 1
                    self._dropped_frames += 1
                    if consecutive_failures >= self._max_consecutive_failures:
                        if not self._reconnect():
                            if self.on_finished is not None:
                                self.on_finished()
                            break
                        consecutive_failures = 0
                    self._stop.wait(period)
                    continue
                consecutive_failures = 0
                timestamp = time.time()
                self._runtime.ingest_frame(frame, timestamp)
                self._frames_read += 1
                self._last_frame_at = time.time()
                self._stop.wait(period)
        finally:
            logger.info(
                "%s camera capture thread exited camera=%s frames_read=%s dropped=%s",
                self.name,
                self._runtime.camera_id,
                self._frames_read,
                self._dropped_frames,
            )


class WebcamCameraSource(LocalOpenCVCameraSource):
    """Laptop webcam transport (``webcam``) - same capture code as droidcam_usb."""

    name = "webcam"
    settings_prefix = "WEBCAM"


__all__ = ["LocalOpenCVCameraSource", "WebcamCameraSource"]
