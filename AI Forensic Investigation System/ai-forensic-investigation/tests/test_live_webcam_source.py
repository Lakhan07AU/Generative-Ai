"""Laptop webcam / USB capture transport tests (``webcam`` + ``droidcam_usb``).

No physical camera is required: a fake ``cv2`` module is injected so the
transport logic (open failure, no-frame-on-open, bounded restarts, health
payload, ingest hand-off) is exercised deterministically. These tests prove the
transport wiring only - physical capture is verified by
``backend/scripts/verify_webcam.py`` on a host that has a real device.
"""

import sys
import time
import types

import numpy as np
import pytest

from app.live.source import CameraSource
from app.live.usb_camera import UsbCameraSource
from app.live.webcam_camera import LocalOpenCVCameraSource, WebcamCameraSource


class FakeRuntime:
    """Minimal stand-in for the live session runtime."""

    def __init__(self):
        self.camera_id = 4242
        self.frames = []

    def ingest_frame(self, frame, timestamp):
        self.frames.append((frame, timestamp))
        return True


class FakeCapture:
    """Fake ``cv2.VideoCapture`` returning a scripted number of frames."""

    def __init__(self, frames=5, fail_after=None, open_ok=True):
        self._frames = frames
        self._fail_after = fail_after
        self._open_ok = open_ok
        self.reads = 0
        self.released = False

    def isOpened(self):
        return self._open_ok

    def get(self, _prop):
        return 30.0

    def set(self, _prop, _value):
        return True

    def read(self):
        self.reads += 1
        if self._fail_after is not None and self.reads > self._fail_after:
            return False, None
        if self.reads > self._frames:
            return False, None
        return True, np.zeros((8, 8, 3), dtype=np.uint8)

    def release(self):
        self.released = True


@pytest.fixture
def fake_cv2(monkeypatch):
    """Install a fake ``cv2`` module and return a factory-configurable holder."""
    holder = types.SimpleNamespace(captures=[], kwargs={})

    def install(**kwargs):
        cap = FakeCapture(**kwargs)
        holder.captures.append(cap)
        module = types.ModuleType("cv2")
        module.VideoCapture = lambda index: cap
        module.CAP_PROP_FPS = 5
        module.CAP_PROP_FRAME_WIDTH = 3
        module.CAP_PROP_FRAME_HEIGHT = 4
        module.__version__ = "fake"
        monkeypatch.setitem(sys.modules, "cv2", module)
        return cap

    return install, holder


# ------------------------------------------------------------------ identity


def test_webcam_is_a_camera_source():
    assert issubclass(WebcamCameraSource, LocalOpenCVCameraSource)
    assert issubclass(LocalOpenCVCameraSource, CameraSource)


def test_webcam_and_usb_share_one_implementation():
    """No second capture pipeline: both transports are the same class."""
    assert issubclass(UsbCameraSource, LocalOpenCVCameraSource)
    assert UsbCameraSource.__mro__[1] is LocalOpenCVCameraSource


def test_transport_names():
    assert WebcamCameraSource.name == "webcam"
    assert UsbCameraSource.name == "droidcam_usb"
    assert WebcamCameraSource.settings_prefix == "WEBCAM"
    assert UsbCameraSource.settings_prefix == "DROIDCAM"


# ------------------------------------------------------------------- opening


def test_connect_raises_when_device_cannot_be_opened(fake_cv2):
    install, _ = fake_cv2
    install(open_ok=False)
    src = WebcamCameraSource(FakeRuntime(), device_index=7)
    with pytest.raises(RuntimeError) as exc:
        src.connect()
    assert "cannot open camera device index 7" in str(exc.value)
    assert src.health()["opened"] is False
    assert src.health()["error"]


def test_connect_raises_when_device_yields_no_frame(fake_cv2):
    """A device that opens but never delivers pixels must NOT be reported open."""
    install, _ = fake_cv2
    install(frames=0, fail_after=0)
    src = WebcamCameraSource(FakeRuntime(), device_index=0)
    with pytest.raises(RuntimeError) as exc:
        src.connect()
    assert "no frame" in str(exc.value)


def test_connect_and_read_frame(fake_cv2):
    install, _ = fake_cv2
    install(frames=3)
    src = WebcamCameraSource(FakeRuntime(), device_index=0)
    src.connect()
    assert src.health()["opened"] is True
    frame = src.read_frame()
    assert frame is not None and frame.shape == (8, 8, 3)
    src.disconnect()
    assert src.health()["opened"] is False


# ------------------------------------------------------------------- thread


def test_start_feeds_frames_into_runtime_ingest(fake_cv2):
    install, _ = fake_cv2
    install(frames=6)
    runtime = FakeRuntime()
    src = WebcamCameraSource(runtime, device_index=0, fps_target=50)
    src.start()
    deadline = time.time() + 3.0
    while len(runtime.frames) < 3 and time.time() < deadline:
        time.sleep(0.01)
    src.stop()
    assert len(runtime.frames) >= 3
    assert src.health()["frames_read"] >= 3
    assert src.health()["source"] == "webcam"
    assert src.health()["device_index"] == 0


def test_health_payload_shape(fake_cv2):
    install, _ = fake_cv2
    install(frames=2)
    src = WebcamCameraSource(FakeRuntime(), device_index=0)
    src.connect()
    health = src.health()
    for key in ("source", "device_index", "opened", "alive", "running",
                "frames_read", "dropped_frames", "restarts", "last_frame_at", "error"):
        assert key in health
    src.disconnect()


def test_reconnect_is_bounded_never_infinite(fake_cv2, monkeypatch):
    """A dead device must give up after MAX_RESTARTS - never loop forever."""
    install, holder = fake_cv2
    install(frames=2)
    monkeypatch.setattr(
        "app.live.webcam_camera.settings.WEBCAM_MAX_RESTARTS", 2, raising=False)
    src = WebcamCameraSource(FakeRuntime(), device_index=0)
    src.connect()
    # Device dies: every subsequent open/read fails.
    holder.captures[0]._fail_after = 0

    attempts = 0
    while src._reconnect() and attempts < 50:  # hard stop proves boundedness
        attempts += 1
    assert attempts <= 2, "reconnect exceeded the configured budget"
    assert src.health()["restarts"] <= 2
    assert src.health()["error"]


def test_midstream_device_failure_stops_session_without_hanging(fake_cv2, monkeypatch):
    """When a live device dies mid-stream the session ends - no infinite loop."""
    install, holder = fake_cv2
    install(frames=2)
    monkeypatch.setattr(
        "app.live.webcam_camera.settings.WEBCAM_MAX_CONSECUTIVE_FAILURES", 1, raising=False)
    monkeypatch.setattr(
        "app.live.webcam_camera.settings.WEBCAM_MAX_RESTARTS", 1, raising=False)
    finished = []
    runtime = FakeRuntime()
    src = WebcamCameraSource(runtime, device_index=0, fps_target=200)
    src.on_finished = lambda: finished.append(True)
    src.start()
    deadline = time.time() + 5.0
    while src.running and time.time() < deadline:
        holder.captures[0]._fail_after = 0  # camera is unplugged after a few frames
        time.sleep(0.01)
    src.stop()
    assert not src.running
    assert finished == [True]
    assert src.health()["error"]
    assert src.health()["restarts"] <= 1


def test_stop_is_idempotent_and_releases_device(fake_cv2):
    install, holder = fake_cv2
    install(frames=4)
    src = WebcamCameraSource(FakeRuntime(), device_index=0, fps_target=50)
    src.start()
    time.sleep(0.1)
    src.stop()
    src.stop()
    assert holder.captures[0].released is True
    assert src.health()["running"] is False


# ------------------------------------------------------------------- wiring


def test_api_accepts_webcam_transport(client, auth_headers):
    """POST /live/cameras/{id}/start accepts transport="webcam"."""
    cam = client.post("/cameras", headers=auth_headers,
                      json={"camera_name": "Webcam wiring", "location": "lab",
                            "camera_type": "OTHER"})
    assert cam.status_code in (200, 201), cam.text
    camera_id = cam.json()["id"]

    resp = client.post(f"/live/cameras/{camera_id}/start", headers=auth_headers,
                       json={"transport": "webcam", "device_index": 0, "fps_target": 10})
    # A machine without a camera must fail loudly (503), never fake a session.
    assert resp.status_code in (200, 201, 503), resp.text
    if resp.status_code == 503:
        assert "unavailable" in resp.json()["detail"].lower()
    else:
        client.post(f"/live/cameras/{camera_id}/stop", headers=auth_headers)


def test_api_still_rejects_unknown_transport(client, auth_headers):
    cam = client.post("/cameras", headers=auth_headers,
                      json={"camera_name": "Bad transport", "location": "lab",
                            "camera_type": "OTHER"})
    camera_id = cam.json()["id"]
    resp = client.post(f"/live/cameras/{camera_id}/start", headers=auth_headers,
                       json={"transport": "nonsense"})
    assert resp.status_code == 422


def test_api_still_accepts_droidcam_usb_transport(client, auth_headers):
    """Backward compatibility: droidcam_usb must keep working."""
    cam = client.post("/cameras", headers=auth_headers,
                      json={"camera_name": "DroidCam wiring", "location": "lab",
                            "camera_type": "OTHER"})
    camera_id = cam.json()["id"]
    resp = client.post(f"/live/cameras/{camera_id}/start", headers=auth_headers,
                       json={"transport": "droidcam_usb", "device_index": 0})
    assert resp.status_code in (200, 201, 503), resp.text
    if resp.status_code != 503:
        client.post(f"/live/cameras/{camera_id}/stop", headers=auth_headers)