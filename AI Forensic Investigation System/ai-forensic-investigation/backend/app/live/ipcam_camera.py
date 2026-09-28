"""Phone IP-camera capture source for live sessions (transport ``ipcam``).

Pulls a network video stream served by a phone (or any IP camera) - for example
the "IP Webcam" app on ``http://<phone-ip>:8080/video`` (MJPEG) or
``rtsp://<phone-ip>:554/...`` (H.264) - and feeds it into exactly the same
ingest, detection, tracking, evidence and audit path as every other transport.

This class is a thin subclass: all capture behaviour lives in
:class:`~app.live.webcam_camera.LocalOpenCVCameraSource`, which is also used by
the ``webcam`` and ``droidcam_usb`` transports. The only differences are:

* the target is a URL rather than a local device index,
* the capture backend order is network/decoder oriented (FFmpeg first),
* a stream URL is mandatory, so a misconfigured camera fails loudly.

Point ``IPCAM_STREAM_URL`` at the device (or pass ``stream_url`` per session) and
start the app; the stream is verified by
``backend/scripts/verify_ipcam.py`` and by ``verify_live_webcam.py --stream-url``.
"""

import logging
from typing import Optional

from app.live.webcam_camera import LocalOpenCVCameraSource

logger = logging.getLogger(__name__)


class IpCameraSource(LocalOpenCVCameraSource):
    """OpenCV capture from a network stream URL (a phone as an IP camera)."""

    name = "ipcam"
    settings_prefix = "IPCAM"

    def __init__(self, runtime, stream_url: Optional[str] = None, **kwargs) -> None:
        super().__init__(runtime, stream_url=stream_url, **kwargs)
        if not self._stream_url:
            raise ValueError(
                "ipcam transport requires a stream URL: pass stream_url or set "
                "IPCAM_STREAM_URL (e.g. http://<phone-ip>:8080/video)"
            )
        if not str(self._stream_url).lower().startswith(("http://", "https://", "rtsp://", "rtmp://")):
            raise ValueError(
                f"ipcam stream URL must be http(s)/rtsp/rtmp, got: {self._stream_url!r}"
            )
        logger.info("ipcam source configured url=%s", self._redact_url(self._stream_url))
