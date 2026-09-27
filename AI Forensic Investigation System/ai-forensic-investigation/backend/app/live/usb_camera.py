"""USB / DroidCam capture source for live sessions (Phase 9 transport).

``DROIDCAM_USB`` advertises that any local OpenCV-compatible capture device can
drive a live session. DroidCam Desktop 4 exposes the phone's camera as a virtual
"USB" device that OpenCV opens with ``cv2.VideoCapture(device_index)`` (typically
index 0).

Implementation note: this transport is now a thin alias of the shared
:class:`~app.live.webcam_camera.LocalOpenCVCameraSource` used by the ``webcam``
transport. There is exactly ONE OpenCV capture implementation in the codebase -
this class only supplies the transport name (``droidcam_usb``) and reads its
defaults from the ``DROIDCAM_*`` settings so existing behaviour, API clients and
tests are unchanged. Both transports feed the same
``runtime.ingest_frame`` ingest path.
"""

import logging

from app.live.webcam_camera import LocalOpenCVCameraSource

logger = logging.getLogger(__name__)


class UsbCameraSource(LocalOpenCVCameraSource):
    """Backward-compatible ``droidcam_usb`` transport (same code as ``webcam``)."""

    name = "droidcam_usb"
    settings_prefix = "DROIDCAM"


__all__ = ["UsbCameraSource", "LocalOpenCVCameraSource"]
