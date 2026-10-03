"""Phone IP-camera transport tests (``ipcam``).

No phone is required: a fake ``cv2`` module is injected so the transport logic
(URL defaults, backend order, mandatory URL, credential redaction, open failure,
ingest hand-off) is exercised deterministically. Real stream reachability is
verified by ``backend/scripts/verify_ipcam.py`` against an actual device.

All URLs below use RFC 5737 documentation ranges (TEST-NET-2/3), which are
never routable to a real host, so no test here can contact a physical camera.
"""

import sys
import types

import numpy as np
import pytest

from app.live import webcam_camera
from app.live.ipcam_camera import IpCameraSource
from app.live.source import CameraSource
from app.live.webcam_camera import LocalOpenCVCameraSource

# RFC 5737 TEST-NET-3: reserved for documentation, never a real device.
URL = "http://203.0.113.10:8080/video"


class FakeRuntime:
    def __init__(self):
        self.camera_id = 4242
        self.frames = []

    def ingest_frame(self, frame, timestamp):
        self.frames.append((frame, timestamp))
        return True


class FakeCapture:
    def __init__(self, frames=5, fail_after=None, open_ok=True, size=1080):
        self._frames = frames
        self._fail_after = fail_after
        self._open_ok = open_ok
        self._size = size
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
        return True, np.zeros((self._size, 1920, 3), dtype=np.uint8)

    def release(self):
        self.released = True


@pytest.fixture
def fake_cv2(monkeypatch):
    """Fake ``cv2`` that records which backend constant opened the URL."""
    holder = types.SimpleNamespace(opened_with=None, cap=None)

    def install(open_ok=True, **kwargs):
        cap = FakeCapture(open_ok=open_ok, **kwargs)

        def _open(target, api=0):
            holder.opened_with = api
            holder.cap = cap
            return cap

        module = types.ModuleType("cv2")
        module.VideoCapture = _open
        module.CAP_PROP_FPS = 5
        module.CAP_PROP_FRAME_WIDTH = 3
        module.CAP_PROP_FRAME_HEIGHT = 4
        module.CAP_ANY = 0
        module.CAP_FFMPEG = 1900
        module.CAP_GSTREAMER = 1800
        module.__version__ = "fake"
        monkeypatch.setitem(sys.modules, "cv2", module)
        return cap

    monkeypatch.setattr(webcam_camera, "_URL_BACKENDS", ("ffmpeg", "any", "gstreamer"))
    return install, holder


# ------------------------------------------------------------------ identity


def test_ipcam_is_a_camera_source():
    assert issubclass(IpCameraSource, LocalOpenCVCameraSource)
    assert IpCameraSource.__mro__[1] is LocalOpenCVCameraSource


def test_ipcam_transport_identity():
    assert IpCameraSource.name == "ipcam"
    assert IpCameraSource.settings_prefix == "IPCAM"


# --------------------------------------------------------------------- config


def test_ffmpeg_and_gstreamer_backends_are_mapped():
    """The URL backend order must resolve, not be dropped as 'unknown'."""
    import cv2

    resolved = webcam_camera._resolve_backends(cv2, ("ffmpeg", "any", "gstreamer"))
    assert [name for name, _ in resolved] == ["ffmpeg", "any", "gstreamer"]


def test_url_streams_default_to_network_backends():
    """A URL stream must not fall back to DirectShow/MSMF."""
    import cv2

    src = IpCameraSource(FakeRuntime(), stream_url=URL)
    assert "dshow" not in src._capture_backends
    assert src._capture_backends[0] == "ffmpeg"


def test_local_devices_keep_platform_backends():
    """A local device must not inherit the URL/decoder backend order."""
    import cv2

    from app.live.webcam_camera import WebcamCameraSource

    src = WebcamCameraSource(FakeRuntime(), device_index=0)
    # No explicit preference: the platform default is resolved at open time.
    assert src._capture_backends is None
    assert "ffmpeg" not in webcam_camera._resolve_backends(cv2, src._capture_backends)[0]


# ------------------------------------------------------------- url validation


def test_missing_url_is_rejected(monkeypatch):
    """No URL in the request and none configured must fail loudly."""
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "IPCAM_STREAM_URL", "", raising=False)
    with pytest.raises(ValueError) as exc:
        IpCameraSource(FakeRuntime())
    assert "requires a stream URL" in str(exc.value)


def test_url_falls_back_to_configured_setting(monkeypatch):
    """IPCAM_STREAM_URL is the default when the request omits a URL."""
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "IPCAM_STREAM_URL", URL, raising=False)
    assert IpCameraSource(FakeRuntime())._stream_url == URL


def test_non_network_url_is_rejected():
    with pytest.raises(ValueError) as exc:
        IpCameraSource(FakeRuntime(), stream_url="/dev/video0")
    assert "http(s)/rtsp/rtmp" in str(exc.value)


@pytest.mark.parametrize("url", [
    "http://203.0.113.10:8080/video",
    "https://cam.example/stream",
    "rtsp://203.0.113.10:554/live",
])
def test_accepted_url_schemes(url, fake_cv2):
    install, _ = fake_cv2
    install()
    assert IpCameraSource(FakeRuntime(), stream_url=url)._stream_url == url


# ------------------------------------------------------------------- opening


def test_connect_opens_the_url_with_ffmpeg(fake_cv2):
    install, holder = fake_cv2
    install()
    src = IpCameraSource(FakeRuntime(), stream_url=URL)
    src.connect()
    assert src.health()["opened"] is True
    assert src.health()["capture_backend"] == "ffmpeg"
    assert holder.opened_with == 1900  # CAP_FFMPEG
    src.disconnect()


def test_connect_raises_when_stream_unreachable(fake_cv2):
    install, _ = fake_cv2
    install(open_ok=False)
    src = IpCameraSource(FakeRuntime(), stream_url=URL)
    with pytest.raises(RuntimeError) as exc:
        src.connect()
    assert "cannot open stream URL" in str(exc.value)
    assert src.health()["opened"] is False


def test_connect_raises_when_no_frame_arrives(fake_cv2):
    install, _ = fake_cv2
    install(fail_after=0)
    src = IpCameraSource(FakeRuntime(), stream_url=URL)
    with pytest.raises(RuntimeError):
        src.connect()


def test_falls_back_to_next_backend(fake_cv2, monkeypatch):
    """If FFmpeg cannot open the stream, ``any`` is tried before giving up."""
    import cv2

    attempts = []

    class Failing(FakeCapture):
        def isOpened(self):
            return False

    def _open(target, api=0):
        attempts.append(api)
        return Failing()

    module = types.ModuleType("cv2")
    module.VideoCapture = _open
    module.CAP_ANY = 0
    module.CAP_FFMPEG = 1900
    module.CAP_GSTREAMER = 1800
    monkeypatch.setitem(sys.modules, "cv2", module)

    src = IpCameraSource(FakeRuntime(), stream_url=URL)
    with pytest.raises(RuntimeError):
        src.connect()
    assert attempts == [1900, 0, 1800]


# --------------------------------------------------------------------- health


def test_health_reports_url_and_backend(fake_cv2):
    install, _ = fake_cv2
    install()
    src = IpCameraSource(FakeRuntime(), stream_url=URL)
    src.connect()
    health = src.health()
    assert health["source"] == "ipcam"
    assert health["stream_url"] == URL
    assert health["capture_backend"] == "ffmpeg"
    src.disconnect()


def test_health_redacts_credentials(fake_cv2):
    install, _ = fake_cv2
    install()
    url = "http://admin:secret@203.0.113.10:8080/video"
    src = IpCameraSource(FakeRuntime(), stream_url=url)
    src.connect()
    health = src.health()
    assert "secret" not in health["stream_url"]
    assert "admin:***@203.0.113.10:8080" in health["stream_url"]
    src.disconnect()


def test_error_message_redacts_credentials(fake_cv2):
    install, _ = fake_cv2
    install(open_ok=False)
    url = "http://admin:secret@203.0.113.10:8080/video"
    src = IpCameraSource(FakeRuntime(), stream_url=url)
    with pytest.raises(RuntimeError) as exc:
        src.connect()
    assert "secret" not in str(exc.value)


# --------------------------------------------------------------------- ingest


def test_frames_reach_the_shared_ingest_path(fake_cv2):
    """Decoded phone frames are handed to the same ingest call as a webcam."""
    import time

    install, _ = fake_cv2
    # connect() spends two frames on its liveness probe, so allow plenty.
    install(frames=40)
    runtime = FakeRuntime()
    src = IpCameraSource(runtime, stream_url=URL, fps_target=30)
    src.start()
    try:
        deadline = time.time() + 5.0
        while len(runtime.frames) < 3 and time.time() < deadline:
            time.sleep(0.01)
    finally:
        src.stop()
    assert len(runtime.frames) >= 3
    assert runtime.frames[0][0].shape == (1080, 1920, 3)


def test_stop_releases_the_stream(fake_cv2):
    install, holder = fake_cv2
    install()
    src = IpCameraSource(FakeRuntime(), stream_url=URL)
    src.start()
    src.stop()
    assert holder.cap.released is True
