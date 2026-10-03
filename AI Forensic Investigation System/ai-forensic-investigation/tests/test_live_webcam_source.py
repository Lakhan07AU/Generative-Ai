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

from app.core.config import settings
from app.live import webcam_camera
from app.live.source import CameraSource
from app.live.usb_camera import UsbCameraSource
from app.live.webcam_camera import LocalOpenCVCameraSource, WebcamCameraSource

# Loopback port 9 (discard) is never listening, so opening it is refused
# immediately by the OS. Keeps the suite hermetic and offline.
UNREACHABLE_LOOPBACK_URL = "http://127.0.0.1:9/video"


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
    """Install a fake ``cv2`` module and return a factory-configurable holder.

    ``backends`` maps a ``cv2.CAP_*`` value to a capture that should be created
    for it, so the multi-backend probe can be exercised.
    """

    holder = types.SimpleNamespace(captures=[], kwargs={}, backends={})

    def install(backends=None, **kwargs):
        cap = FakeCapture(**kwargs)
        holder.captures.append(cap)
        holder.backends = backends or {}
        module = types.ModuleType("cv2")
        module.VideoCapture = lambda index, api=0: cap
        module.CAP_PROP_FPS = 5
        module.CAP_PROP_FRAME_WIDTH = 3
        module.CAP_PROP_FRAME_HEIGHT = 4
        module.CAP_ANY = 0
        module.CAP_DSHOW = 700
        module.CAP_MSMF = 1400
        module.CAP_V4L2 = 200
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


# ------------------------------------------------------- capture backend probe


def test_backend_fallback_finds_a_backend_that_delivers_frames(monkeypatch):
    """Windows UVC: a backend can open the device yet never deliver a frame.

    The probe must fall through to the next backend and report the one it
    actually used - here DSHOW (tried first on Windows) stalls, MSMF works.
    """
    tries = []

    class _Stalling(FakeCapture):
        def read(self):
            self.reads += 1
            return False, None

    class _Working(FakeCapture):
        pass

    stalling, working = _Stalling(open_ok=True), _Working(open_ok=True, frames=5)
    module = types.ModuleType("cv2")
    module.CAP_ANY = 0
    module.CAP_MSMF = 1400
    module.CAP_DSHOW = 700
    module.CAP_PROP_FPS = 5
    module.CAP_PROP_FRAME_WIDTH = 3
    module.CAP_PROP_FRAME_HEIGHT = 4

    def _video_capture(index, api=0):
        tries.append(api)
        return stalling if api == 700 else working

    module.VideoCapture = _video_capture
    monkeypatch.setitem(sys.modules, "cv2", module)
    monkeypatch.setattr(webcam_camera.sys, "platform", "win32")

    src = WebcamCameraSource(FakeRuntime(), device_index=0)
    src.connect()
    try:
        assert tries == [700, 1400], f"DSHOW must be probed first on Windows, then MSMF: {tries}"
        assert src.health()["capture_backend"] == "msmf"
        assert src.health()["opened"] is True
        assert src.read_frame() is not None
    finally:
        src.disconnect()
    assert working.released is True
    assert stalling.released is True, "a stalled attempt must be released"


def test_all_backends_failing_names_them_in_the_error(monkeypatch):
    class _Dead(FakeCapture):
        def read(self):
            return False, None

    dead = _Dead(open_ok=True)
    module = types.ModuleType("cv2")
    module.CAP_ANY = 0
    module.CAP_DSHOW = 700
    module.CAP_PROP_FPS = 5
    module.CAP_PROP_FRAME_WIDTH = 3
    module.CAP_PROP_FRAME_HEIGHT = 4
    module.VideoCapture = lambda index, api=0: dead
    monkeypatch.setitem(sys.modules, "cv2", module)
    monkeypatch.setattr(webcam_camera.sys, "platform", "win32")

    src = WebcamCameraSource(FakeRuntime(), device_index=2)
    with pytest.raises(RuntimeError) as exc:
        src.connect()
    message = str(exc.value)
    assert "cannot open camera device index 2" in message
    assert "dshow" in message and "any" in message
    assert dead.released is True


def test_explicit_backend_setting_is_honoured(monkeypatch):
    tries = []
    cap = FakeCapture(frames=5)
    module = types.ModuleType("cv2")
    module.CAP_ANY = 0
    module.CAP_MSMF = 1400
    module.CAP_DSHOW = 700
    module.CAP_PROP_FPS = 5
    module.CAP_PROP_FRAME_WIDTH = 3
    module.CAP_PROP_FRAME_HEIGHT = 4
    module.VideoCapture = lambda index, api=0: (tries.append(api), cap)[1]
    monkeypatch.setitem(sys.modules, "cv2", module)
    monkeypatch.setattr(webcam_camera.settings, "WEBCAM_CAPTURE_BACKENDS", "msmf")

    src = WebcamCameraSource(FakeRuntime(), device_index=0)
    src.connect()
    try:
        assert tries == [1400]
        assert src.health()["capture_backend"] == "msmf"
    finally:
        src.disconnect()


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


def test_reconnect_backoff_survives_a_transient_source_outage(fake_cv2, monkeypatch):
    """A brief outage must not burn the whole restart budget instantly.

    A phone app serving /video drops the stream when its screen locks or Wi-Fi
    blips. With no delay between attempts, all 3 restarts were consumed in well
    under a second, so a 2-3s hiccup permanently ended the session.
    """
    install, holder = fake_cv2
    install(frames=2)
    monkeypatch.setattr(
        "app.live.webcam_camera.settings.WEBCAM_MAX_RESTARTS", 4, raising=False)
    monkeypatch.setattr(
        "app.live.webcam_camera.settings.WEBCAM_RECONNECT_BACKOFF_SECONDS", 0.05,
        raising=False)
    src = WebcamCameraSource(FakeRuntime(), device_index=0)
    src.connect()
    holder.captures[0]._fail_after = 0

    # Drive on the attempt counter: connect() keeps failing, so the return
    # value is not what advances the loop.
    started = time.time()
    attempts = 0
    while src._restarts < 4:
        src._reconnect()
        attempts += 1
        assert attempts < 20, "reconnect did not terminate"
    elapsed = time.time() - started

    assert attempts == 4
    # Backoff is linear in the attempt number: 0.05 + 0.10 + 0.15 + 0.20.
    assert elapsed >= 0.45, f"attempts fired too fast to ride out a hiccup ({elapsed:.3f}s)"


def test_reconnect_backoff_wait_is_interrupted_by_stop(fake_cv2, monkeypatch):
    """stop() during a long backoff must not wait out the full delay."""
    install, holder = fake_cv2
    install(frames=2)
    monkeypatch.setattr(
        "app.live.webcam_camera.settings.WEBCAM_RECONNECT_BACKOFF_SECONDS", 30.0,
        raising=False)
    src = WebcamCameraSource(FakeRuntime(), device_index=0)
    src.connect()
    holder.captures[0]._fail_after = 0
    src.start()
    time.sleep(0.05)
    src.stop()
    assert not src.running, "stop() hung waiting on the reconnect backoff"


def test_restart_budget_is_restored_after_a_stable_recovery(fake_cv2, monkeypatch):
    """Only *consecutive* failures should end a long session.

    Without restoring the budget, a session that ran flawlessly for hours still
    died on its Nth hiccup ever, which is the normal case for a phone stream.
    """
    install, holder = fake_cv2
    install(frames=4)
    monkeypatch.setattr(
        "app.live.webcam_camera.settings.WEBCAM_RECONNECT_RESET_SECONDS", 60.0,
        raising=False)
    src = WebcamCameraSource(FakeRuntime(), device_index=0)
    src.connect()
    src._restarts = 2  # two hiccups earlier in the session

    src._reconnected_at = time.time()
    src._forget_recovered_outage(time.time() + 10.0)
    assert src._restarts == 2, "budget restored before the source proved stable"

    src._forget_recovered_outage(time.time() + 61.0)
    assert src._restarts == 0, "budget not restored after a stable recovery"
    assert src.health()["restarts"] == 0


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


def test_api_accepts_ipcam_transport_with_stream_url(client, auth_headers):
    """POST /live/cameras/{id}/start accepts transport="ipcam" + stream_url.

    The URL points at a loopback port that is guaranteed closed, so this test
    never touches a real network device and never depends on a phone being on.
    An unreachable stream must fail loudly (503), never fake a session.
    """
    cam = client.post("/cameras", headers=auth_headers,
                      json={"camera_name": "IPCam wiring", "location": "lab",
                            "camera_type": "OTHER"})
    assert cam.status_code in (200, 201), cam.text
    camera_id = cam.json()["id"]

    resp = client.post(f"/live/cameras/{camera_id}/start", headers=auth_headers,
                       json={"transport": "ipcam",
                             "stream_url": UNREACHABLE_LOOPBACK_URL,
                             "fps_target": 10})
    assert resp.status_code == 503, resp.text
    assert "unavailable" in resp.json()["detail"].lower()


def test_api_rejects_ipcam_without_stream_url(client, auth_headers, monkeypatch):
    """ipcam with no URL anywhere must not silently open a local device."""
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "IPCAM_STREAM_URL", "", raising=False)
    cam = client.post("/cameras", headers=auth_headers,
                      json={"camera_name": "IPCam no URL", "location": "lab",
                            "camera_type": "OTHER"})
    camera_id = cam.json()["id"]
    resp = client.post(f"/live/cameras/{camera_id}/start", headers=auth_headers,
                       json={"transport": "ipcam"})
    assert resp.status_code == 503
    assert "stream url" in resp.json()["detail"].lower()