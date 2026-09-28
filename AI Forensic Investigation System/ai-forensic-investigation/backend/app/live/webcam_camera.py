"""Laptop webcam capture source for live sessions (transport ``webcam``).

``webcam``, ``droidcam_usb`` and ``ipcam`` share ONE implementation - there is no
second capture pipeline in the codebase::

    webcam            droidcam_usb              ipcam
       \\               /                          /
        LocalOpenCVCameraSource        (app/live/webcam_camera.py)
                    |
                    v
          runtime.ingest_frame(frame, ts)
                    |
          FrameIngestion -> FrameSampler -> RollingFrameBuffer -> YOLO -> tracking

``webcam``/``droidcam_usb`` open a local OpenCV-compatible capture device with
``cv2.VideoCapture(device_index)``; ``ipcam`` (see
:mod:`app.live.ipcam_camera`) opens a network stream URL served by a phone
running an IP-camera app. All of them push frames into exactly the same ingest
path the demo file transport uses, so a laptop webcam, a USB capture card, a
DroidCam virtual camera and a phone IP camera share identical sampling,
detection, tracking, evidence and audit behaviour.

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
import sys
import threading
import time
from typing import Optional

from app.core.config import settings
from app.live.source import CameraSource

logger = logging.getLogger(__name__)

# Capture backends, most reliable first for the running OS. On Windows a UVC
# camera regularly "opens" through the default/MSMF backend but never delivers a
# frame, while DSHOW works - so the backend is part of the probe, not a guess.
_BACKEND_NAMES = {
    "dshow": "CAP_DSHOW",
    "msmf": "CAP_MSMF",
    "d3d11": "CAP_D3D11",
    "v4l2": "CAP_V4L2",
    "avfoundation": "CAP_AVFOUNDATION",
    "ffmpeg": "CAP_FFMPEG",
    "gstreamer": "CAP_GSTREAMER",
    "any": "CAP_ANY",
    "default": "CAP_ANY",
}

_PLATFORM_DEFAULT_BACKENDS = {
    "win32": ("dshow", "msmf", "any"),
    "darwin": ("avfoundation", "any"),
}
_FALLBACK_BACKENDS = ("any", "v4l2")
# URL streams (a phone running an IP-camera app) are opened over the network, so
# DirectShow/MSMF are pointless for them; FFmpeg's demuxers handle the formats
# these apps serve (MJPEG, H.264) best.
_URL_BACKENDS = ("ffmpeg", "any", "gstreamer")


def _default_backends() -> tuple:
    return _PLATFORM_DEFAULT_BACKENDS.get(sys.platform, _FALLBACK_BACKENDS)


def _resolve_backends(cv2_module, requested) -> list:
    """Map backend names to ``cv2.CAP_*`` constants, skipping unavailable ones."""
    wanted = tuple(requested) if requested else _default_backends()
    out = []
    for name in wanted:
        attr = _BACKEND_NAMES.get(str(name).strip().lower())
        if attr is None:
            logger.warning("unknown capture backend %r, ignoring", name)
            continue
        api = getattr(cv2_module, attr, None)
        if api is None or int(api) < 0:
            logger.debug("capture backend %s not available in this OpenCV build", name)
            continue
        out.append((str(name).strip().lower(), int(api)))
    if not out:  # never leave the source without a way to open a device
        out.append(("any", int(getattr(cv2_module, "CAP_ANY", 0))))
    return out


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
        stream_url: Optional[str] = None,
    ) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise ImportError(
                "OpenCV (cv2) is required for the webcam/droidcam_usb/ipcam transport"
            ) from exc
        self._cv2 = cv2
        self._runtime = runtime
        self._prefix = (settings_prefix or self.settings_prefix).upper()
        if name is not None:
            self.name = name

        def _setting(suffix: str, default):
            value = getattr(settings, f"{self._prefix}_{suffix}", None)
            return default if value is None else value

        self._stream_url = (stream_url if stream_url is not None else _setting("STREAM_URL", "")) or ""
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
        # A phone IP-camera app closes its stream when the screen locks, is
        # backgrounded, or simply hiccups. Reconnecting with no delay burns all
        # attempts in well under a second, so any hiccup longer than that ends
        # the session permanently. Wait between attempts (capped) so a brief
        # outage is survivable.
        self._reconnect_backoff = float(_setting("RECONNECT_BACKOFF_SECONDS", 0.0) or 0.0)
        # Once the source has streamed again for this long, the earlier outage
        # is forgiven and the restart budget is restored. Without this a long
        # session dies on its Nth hiccup ever, even if it ran flawlessly in
        # between for hours.
        self._reconnect_reset_seconds = float(_setting("RECONNECT_RESET_SECONDS", 60.0) or 0.0)
        configured = _setting("CAPTURE_BACKENDS", None)
        if isinstance(configured, str):
            configured = tuple(p.strip() for p in configured.split(",") if p.strip())
        # A URL stream is not a local device: DirectShow/MSMF are meaningless for
        # it, so the default order switches to network/decoder backends.
        self._capture_backends = (
            tuple(configured) if configured else (_URL_BACKENDS if self._stream_url else None)
        )
        self._capture_backend: Optional[str] = None
        self.on_finished = on_finished
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cap = None
        self._opened = False
        self._started_at = 0.0
        self._frames_read = 0
        self._dropped_frames = 0
        self._restarts = 0
        self._reconnected_at: Optional[float] = None
        self._last_frame_at = 0.0
        self._health_error: Optional[str] = None

    # -- CameraSource contract ----------------------------------------------

    def _open_capture(self):
        """Return a capture that genuinely yields pixels, or raise.

        OpenCV's default backend is not trustworthy across platforms: on Windows
        many UVC cameras report ``isOpened() == True`` under ``CAP_ANY``/
        ``CAP_MSMF`` yet never deliver a frame, while ``CAP_DSHOW`` works. Each
        configured backend is therefore probed with a real read and the first
        one that produces pixels wins.

        When ``stream_url`` is set the capture target is that URL (a phone
        running an IP-camera app) instead of a local device index.
        """
        cv2_mod = self._cv2
        target = self._stream_url if self._stream_url else self._device_index
        attempts = []
        for name, api in _resolve_backends(cv2_mod, self._capture_backends):
            try:
                cap = cv2_mod.VideoCapture(target, api)
            except Exception as exc:  # noqa: BLE001 - try the next backend
                attempts.append(f"{name}: {exc}")
                continue
            if cap is None or not cap.isOpened():
                attempts.append(f"{name}: not opened")
                if cap is not None:
                    cap.release()
                continue
            try:
                ok, frame = cap.read()
            except Exception as exc:  # noqa: BLE001
                attempts.append(f"{name}: read failed ({exc})")
                cap.release()
                continue
            if ok and frame is not None and getattr(frame, "size", 0) > 0:
                self._capture_backend = name
                return cap, frame
            attempts.append(f"{name}: opened but no frame")
            cap.release()
        if self._stream_url:
            where = f"stream URL {self._redact_url(self._stream_url)}"
        else:
            where = f"camera device index {self._device_index}"
        raise RuntimeError(
            f"cannot open {where} with any capture backend "
            f"({'; '.join(attempts) or 'no backend available'}); the device may not "
            f"exist, the URL may be unreachable, or it may be in use by another application"
        )

    def connect(self) -> None:
        """Open the capture device. Raises if the device cannot be opened.

        A real frame read is required before the device is declared open, so a
        non-existent device - or one whose default capture backend silently
        stalls - can never be reported as a working webcam.
        """
        try:
            cap, first_frame = self._open_capture()
            native_fps = cap.get(self._cv2.CAP_PROP_FPS) or 0.0
            target = float(self._fps_target or self._prefix_fps or native_fps or 0.0)
            if target > 0:
                cap.set(self._cv2.CAP_PROP_FPS, target)
            if self._width > 0:
                cap.set(self._cv2.CAP_PROP_FRAME_WIDTH, float(self._width))
            if self._height > 0:
                cap.set(self._cv2.CAP_PROP_FRAME_HEIGHT, float(self._height))
            # A backend can hand over a frame and then stall; re-read once after
            # applying the format so a dead handle is rejected here too.
            ok, frame = cap.read()
            if not ok or frame is None or getattr(frame, "size", 0) == 0:
                frame = first_frame
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
        """Release the capture device (idempotent).

        A running capture thread is halted as well: leaving it alive would have
        it read from a released handle and potentially reopen the device behind
        the caller's back.
        """
        if self._thread is not None and self._thread.is_alive():
            self._stop.set()
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

    def is_alive(self) -> bool:
        if self._thread is None or not self._thread.is_alive():
            return False
        if self._last_frame_at <= 0:
            return False
        return (time.time() - self._last_frame_at) <= self._stale_seconds

    @staticmethod
    def _redact_url(url: str) -> str:
        """Hide any user:password pair before the URL reaches health or logs."""
        if not url or "//" not in url:
            return url
        scheme, _, rest = url.partition("//")
        creds, sep, host = rest.partition("@")
        if not sep or ":" not in creds:
            return url
        user = creds.split(":", 1)[0]
        return f"{scheme}//{user}:***@{host}"

    def health(self) -> dict:
        return {
            "source": self.name,
            "device_index": self._device_index,
            "stream_url": self._redact_url(self._stream_url) or None,
            "capture_backend": self._capture_backend,
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
        """Bounded reconnect with backoff. Never loops forever.

        ``max_restarts`` is the number of attempts, and each one is preceded by
        a wait so a transient source outage (a phone locking its screen, a brief
        Wi-Fi gap) can be ridden out instead of exhausting the budget in
        milliseconds. The wait is interruptible via ``stop()``.
        """
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
        backoff = max(self._reconnect_backoff, 0.0) * self._restarts
        if backoff > 0:
            logger.warning(
                "%s camera camera=%s waiting %.1fs before reconnect attempt %s/%s",
                self.name,
                self._runtime.camera_id,
                backoff,
                self._restarts,
                self._max_restarts,
            )
            # Interruptible: stop() during the backoff ends the wait at once.
            if self._stop.wait(backoff):
                return False
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
            self._reconnected_at = time.time()
            return True
        except Exception as exc:  # noqa: BLE001
            self._health_error = str(exc)
            return False

    # -- Capture loop --------------------------------------------------------

    def _forget_recovered_outage(self, now: float) -> None:
        """Restore the restart budget once the source has stayed healthy.

        A long session should not die because the total number of hiccups over
        its lifetime reached ``max_restarts``; only a run of *consecutive*
        failures should exhaust it. Once frames have flowed again for
        ``RECONNECT_RESET_SECONDS``, the previous outage is forgiven.
        """
        if self._reconnected_at is None or self._reconnect_reset_seconds <= 0:
            return
        if now - self._reconnected_at < self._reconnect_reset_seconds:
            return
        logger.info(
            "%s camera camera=%s stable for %.0fs after reconnect; restoring restart budget",
            self.name,
            self._runtime.camera_id,
            now - self._reconnected_at,
        )
        self._restarts = 0
        self._reconnected_at = None

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
                self._forget_recovered_outage(timestamp)
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
