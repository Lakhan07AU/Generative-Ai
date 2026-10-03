"""RTSP transport tests (``rtsp``).

No camera is required: a fake ``cv2`` module is injected so the transport logic
(strict scheme validation, FFmpeg-first backend order, rtsp_transport=tcp URL
augmentation, open failure, credential redaction, ingest hand-off, open-timeout
hint) is exercised deterministically. Real stream reachability is verified by
``backend/scripts/verify_rtsp_camera.py`` against an actual camera.

All URLs below use RFC 5737 documentation ranges (TEST-NET-3), which are never
routable to a real host, so no test here can contact a physical camera.
"""

import sys
import types

import numpy as np
import pytest

from app.live import rtsp_camera, webcam_camera
from app.live.rtsp_camera import RtspCameraSource, rtsp_url_with_transport
from app.live.webcam_camera import LocalOpenCVCameraSource

# RFC 5737 TEST-NET-3: reserved for documentation, never a real device.
URL = "rtsp://203.0.113.10:554/stream"
TCP_URL = "rtsp://203.0.113.10:554/stream?rtsp_transport=tcp"


class FakeRuntime:
    def __init__(self):
        self.camera_id = 4243
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
        self.sets = []

    def isOpened(self):
        return self._open_ok

    def get(self, _prop):
        return 30.0

    def set(self, prop, value):
        self.sets.append((prop, value))
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
    """Fake ``cv2`` that records which backend constant and target opened."""
    holder = types.SimpleNamespace(opened_with=None, opened_target=None, cap=None)

    def install(open_ok=True, **kwargs):
        cap = FakeCapture(open_ok=open_ok, **kwargs)

        def _open(target, api=0):
            holder.opened_with = api
            holder.opened_target = target
            holder.cap = cap
            return cap

        module = types.ModuleType("cv2")
        module.VideoCapture = _open
        module.CAP_PROP_FPS = 5
        module.CAP_PROP_FRAME_WIDTH = 3
        module.CAP_PROP_FRAME_HEIGHT = 4
        module.CAP_PROP_OPEN_TIMEOUT_MSEC = 7
        module.CAP_ANY = 0
        module.CAP_FFMPEG = 1900
        module.CAP_GSTREAMER = 1800
        module.__version__ = "fake"
        monkeypatch.setitem(sys.modules, "cv2", module)
        return cap

    monkeypatch.setattr(webcam_camera, "_URL_BACKENDS", ("ffmpeg", "any", "gstreamer"))
    return install, holder


# ------------------------------------------------------------------ identity


def test_rtsp_is_a_camera_source():
    assert issubclass(RtspCameraSource, LocalOpenCVCameraSource)
    assert RtspCameraSource.__mro__[1] is LocalOpenCVCameraSource


def test_rtsp_transport_identity():
    assert RtspCameraSource.name == "rtsp"
    assert RtspCameraSource.settings_prefix == "RTSP"


def test_rtsp_defaults_to_ffmpeg_network_backends(fake_cv2):
    install, _ = fake_cv2
    install()
    src = RtspCameraSource(FakeRuntime(), stream_url=URL)
    assert "dshow" not in src._capture_backends
    assert src._capture_backends[0] == "ffmpeg"
    assert tuple(src._capture_backends) == ("ffmpeg", "any", "gstreamer")


# ------------------------------------------------------------- url validation


def test_missing_url_is_rejected(monkeypatch):
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "RTSP_STREAM_URL", "", raising=False)
    with pytest.raises(ValueError) as exc:
        RtspCameraSource(FakeRuntime())
    assert "requires a stream URL" in str(exc.value)


def test_url_falls_back_to_configured_setting(monkeypatch):
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "RTSP_STREAM_URL", URL, raising=False)
    assert RtspCameraSource(FakeRuntime())._stream_url == URL


def test_non_rtsp_url_is_rejected(monkeypatch):
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "RTSP_STREAM_URL", "", raising=False)
    for bad in ("http://203.0.113.10:8080/video", "/dev/video0", "rtsp:/stream", "rtp://h/live"):
        with pytest.raises(ValueError) as exc:
            RtspCameraSource(FakeRuntime(), stream_url=bad)
        assert "rtsp:// or rtsps://" in str(exc.value)


def test_empty_url_is_rejected_as_missing(monkeypatch):
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "RTSP_STREAM_URL", "", raising=False)
    with pytest.raises(ValueError) as exc:
        RtspCameraSource(FakeRuntime(), stream_url="")
    assert "requires a stream URL" in str(exc.value)


@pytest.mark.parametrize("url", [
    "rtsp://203.0.113.10:554/stream",
    "rtsps://cam.example:8322/onvif1",
    "rtsp://admin:secret@203.0.113.10:554/live/1",
])
def test_accepted_url_schemes(url, fake_cv2):
    install, _ = fake_cv2
    install()
    assert RtspCameraSource(FakeRuntime(), stream_url=url)._stream_url == url


# ------------------------------------------------- transport-tcp augmentation


@pytest.mark.parametrize("url,expected", [
    ("rtsp://203.0.113.10:554/stream", "rtsp://203.0.113.10:554/stream?rtsp_transport=tcp"),
    ("rtsp://h:554/a?keep=1", "rtsp://h:554/a?keep=1&rtsp_transport=tcp"),
    ("rtsp://h:554/a?rtsp_transport=udp", "rtsp://h:554/a?rtsp_transport=udp"),
])
def test_rtsp_url_with_transport_adds_tcp_once(url, expected):
    assert rtsp_url_with_transport(url, True) == expected


def test_rtsp_url_with_transport_respects_udp_override():
    assert rtsp_url_with_transport("rtsp://h:554/a?rtsp_transport=udp", True) == (
        "rtsp://h:554/a?rtsp_transport=udp"
    )


def test_rtsp_url_with_transport_off_leaves_url_untouched():
    assert rtsp_url_with_transport(URL, False) == URL
    assert rtsp_url_with_transport("", True) == ""


def test_connect_opens_the_effective_tcp_url(fake_cv2):
    install, holder = fake_cv2
    install()
    src = RtspCameraSource(FakeRuntime(), stream_url=URL)
    assert src._effective_url == TCP_URL
    src.connect()
    assert holder.opened_target == TCP_URL
    assert src.health()["capture_backend"] == "ffmpeg"
    assert holder.opened_with == 1900  # CAP_FFMPEG
    src.disconnect()


# ------------------------------------------------------------------- opening


def test_connect_raises_when_stream_unreachable(fake_cv2):
    install, _ = fake_cv2
    install(open_ok=False)
    src = RtspCameraSource(FakeRuntime(), stream_url=URL)
    with pytest.raises(RuntimeError) as exc:
        src.connect()
    assert "cannot open stream URL" in str(exc.value)
    assert src.health()["opened"] is False


def test_connect_raises_when_no_frame_arrives(fake_cv2):
    install, _ = fake_cv2
    install(fail_after=0)
    src = RtspCameraSource(FakeRuntime(), stream_url=URL)
    with pytest.raises(RuntimeError):
        src.connect()


def test_falls_back_to_next_backend(fake_cv2, monkeypatch):
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

    src = RtspCameraSource(FakeRuntime(), stream_url=URL)
    with pytest.raises(RuntimeError):
        src.connect()
    assert attempts == [1900, 0, 1800]


def test_open_timeout_hint_applied(fake_cv2, monkeypatch):
    from app.core import config as config_module

    install, holder = fake_cv2
    install()
    monkeypatch.setattr(
        config_module.settings, "RTSP_OPEN_TIMEOUT_SECONDS", 7.5, raising=False
    )
    src = RtspCameraSource(FakeRuntime(), stream_url=URL)
    src.connect()
    assert any(prop == 7 and value == 7500.0 for prop, value in holder.cap.sets)
    src.disconnect()


# --------------------------------------------------------------------- health


def test_health_reports_url_and_backend(fake_cv2):
    install, _ = fake_cv2
    install()
    src = RtspCameraSource(FakeRuntime(), stream_url=URL)
    src.connect()
    health = src.health()
    assert health["source"] == "rtsp"
    assert health["stream_url"] == TCP_URL
    assert health["capture_backend"] == "ffmpeg"
    assert health["transport_tcp"] is True
    src.disconnect()


def test_health_redacts_credentials(fake_cv2):
    install, _ = fake_cv2
    install()
    url = "rtsp://admin:secret@203.0.113.10:554/live"
    src = RtspCameraSource(FakeRuntime(), stream_url=url)
    src.connect()
    health = src.health()
    assert "secret" not in health["stream_url"]
    assert "admin:***@203.0.113.10" in health["stream_url"]
    src.disconnect()


def test_error_message_redacts_credentials(fake_cv2):
    install, _ = fake_cv2
    install(open_ok=False)
    url = "rtsp://admin:secret@203.0.113.10:554/live"
    src = RtspCameraSource(FakeRuntime(), stream_url=url)
    with pytest.raises(RuntimeError) as exc:
        src.connect()
    assert "secret" not in str(exc.value)


# --------------------------------------------------------------------- ingest


def test_frames_reach_the_shared_ingest_path(fake_cv2):
    """Decoded RTSP frames are handed to the same ingest call as a webcam."""
    import time

    install, _ = fake_cv2
    # connect() spends two frames on its liveness probe, so allow plenty.
    install(frames=40)
    runtime = FakeRuntime()
    src = RtspCameraSource(runtime, stream_url=URL, fps_target=30)
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
    src = RtspCameraSource(FakeRuntime(), stream_url=URL)
    src.start()
    src.stop()
    assert holder.cap.released is True