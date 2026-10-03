"""RTSP capture source for live sessions and auto-processed CCTV (transport ``rtsp``).

CCTV cameras expose RTSP streams (H.264/H.265); this transport pulls such a
stream through OpenCV's FFmpeg capture backend and feeds it into the exact same
ingest, detection, tracking, evidence and audit path as every other transport::

    rtsp://<cam>:554/...  ->  RtspCameraSource  ->  runtime.ingest_frame(...)
                                                  -> FrameIngestion -> YOLO -> tracking

The class reuses ALL capture behaviour from
:class:`~app.live.webcam_camera.LocalOpenCVCameraSource` - the same code that
backs ``webcam``, ``droidcam_usb`` and ``ipcam`` - so the reconnect/backoff
policy, credential redaction, backend probing and health reporting are shared.
The only additions are RTSP-specific hardening:

* the scheme is strictly ``rtsp://`` or ``rtsps://`` (an HTTP MJPEG stream is
  the ``ipcam`` transport, not this one),
* FFmpeg network backends are tried first (``ffmpeg``, ``any``, ``gstreamer``),
* when ``RTSP_TRANSPORT_TCP`` is set (default) the stream URL is augmented with
  ``rtsp_transport=tcp`` so RTP rides over reliable TCP instead of lossy UDP -
  this substantially improves frame continuity across Wi-Fi and NAT,
* ``RTSP_OPEN_TIMEOUT_SECONDS`` bounds the FFmpeg open handshake when the
  backend exposes ``CAP_PROP_OPEN_TIMEOUT_MSEC``.

Point ``RTSP_STREAM_URL`` at the device (or pass ``stream_url`` per session) and
start the app. Concrete reachability is verified by
``backend/scripts/verify_rtsp_camera.py`` against a real camera; the
auto-processing supervisor (``app/live/auto_process.py``) drives this source for
cameras flagged ``auto_process``.
"""

import logging
import re
from typing import Optional

from app.core.config import settings
from app.live.webcam_camera import LocalOpenCVCameraSource, _resolve_backends

logger = logging.getLogger(__name__)

_RTSP_RE = re.compile(r"^rtsp://|^rtsps://", re.IGNORECASE)


def rtsp_url_with_transport(url: str, transport_tcp: bool) -> str:
    """Append FFmpeg ``rtsp_transport=tcp`` to an RTSP URL (idempotent).

    OpenCV's FFmpeg demuxer honours ``rtsp_transport`` passed as a URL query
    parameter, so forcing TCP is done by manipulating the URL rather than a
    capture property. The option is only added once; if the URL already carries
    an explicit ``rtsp_transport`` override it is left untouched so an operator
    choice is never silently overridden.
    """
    url = (url or "").strip()
    if not transport_tcp or not url or "rtsp_transport=" in url:
        return url
    marker = "?" if "?" not in url.split("/", 3)[-1] else "&"
    return f"{url}{marker}rtsp_transport=tcp"


class RtspCameraSource(LocalOpenCVCameraSource):
    """OpenCV/FFmpeg capture from an RTSP stream URL (a CCTV camera)."""

    name = "rtsp"
    settings_prefix = "RTSP"

    def __init__(self, runtime, stream_url: Optional[str] = None, **kwargs) -> None:
        url = str(stream_url if stream_url is not None else getattr(settings, "RTSP_STREAM_URL", "") or "").strip()
        if not url:
            raise ValueError(
                "rtsp transport requires a stream URL: pass stream_url or set "
                "RTSP_STREAM_URL (e.g. rtsp://<camera-ip>:554/stream)"
            )
        if not _RTSP_RE.match(url):
            raise ValueError(
                f"rtsp stream URL must start with rtsp:// or rtsps://, got: {url!r}"
            )
        super().__init__(runtime, stream_url=stream_url, **kwargs)
        # Only FFmpeg-family backends make sense for RTSP (DirectShow/MSMF have
        # never opened an RTSP URL), and the demuxer is tried first on every
        # platform. The URL default already does this; pin it explicitly so a
        # configured RTSP_CAPTURE_BACKENDS can never downgrade the order.
        self._capture_backends = ("ffmpeg", "any", "gstreamer")
        self._transport_tcp = bool(getattr(settings, "RTSP_TRANSPORT_TCP", True))
        self._open_timeout_seconds = float(
            getattr(settings, "RTSP_OPEN_TIMEOUT_SECONDS", 0.0) or 0.0
        )
        self._effective_url = rtsp_url_with_transport(url, self._transport_tcp)
        if self._effective_url != url:
            logger.info(
                "rtsp source %s transport forced to tcp",
                self._redact_url(self._effective_url),
            )
        logger.info("rtsp source configured url=%s", self._redact_url(self._effective_url))

    def connect(self) -> None:
        """Open the RTSP URL with the transport override applied."""
        original = self._stream_url
        self._stream_url = self._effective_url
        try:
            super().connect()
        finally:
            self._stream_url = original
        # Post-open hint for backends that honour CAP_PROP_OPEN_TIMEOUT_MSEC
        # when set after creation (best effort only; the pre-open bound happens
        # in _open_capture, which is what actually limits the handshake).
        cap = getattr(self, "_cap", None)
        if cap is not None and self._open_timeout_seconds > 0:
            prop = getattr(self._cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
            if prop is not None:
                try:
                    cap.set(prop, float(self._open_timeout_seconds * 1000.0))
                except Exception:  # noqa: BLE001 - hint only, never fatal
                    pass

    def _open_capture(self):
        """Open the effective RTSP URL, passing the open timeout to OpenCV.

        The FFmpeg backend's default connect handshake can block for tens of
        seconds against an unresponsive host. ``RTSP_OPEN_TIMEOUT_SECONDS`` is
        therefore passed into ``cv2.VideoCapture`` as
        ``CAP_PROP_OPEN_TIMEOUT_MSEC`` *before* the liveness probe (the
        3-arg param list form used by OpenCV >= 4.5.1), falling back to the
        2-arg form on builds that predate it. The liveness probing itself is
        identical to the shared base implementation.
        """
        cv2_mod = self._cv2
        target = self._stream_url if self._stream_url else self._device_index
        attempts = []
        timeout_prop = None
        if self._open_timeout_seconds > 0:
            timeout_prop = getattr(cv2_mod, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
        for name, api in _resolve_backends(cv2_mod, self._capture_backends):
            try:
                if timeout_prop is not None:
                    timeout_ms = int(round(self._open_timeout_seconds * 1000.0))
                    try:
                        cap = cv2_mod.VideoCapture(target, api, [timeout_prop, timeout_ms])
                    except TypeError:
                        cap = cv2_mod.VideoCapture(target, api)
                else:
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
        raise RuntimeError(
            f"cannot open stream URL {self._redact_url(self._effective_url)} "
            f"with any capture backend "
            f"({'; '.join(attempts) or 'no backend available'}); the device may not "
            f"exist, the URL may be unreachable, or it may be in use by another application"
        )

    def health(self) -> dict:
        info = super().health()
        info["stream_url"] = self._redact_url(self._effective_url) or None
        info["transport_tcp"] = self._transport_tcp
        info["open_timeout_seconds"] = self._open_timeout_seconds
        return info


__all__ = ["RtspCameraSource", "rtsp_url_with_transport"]