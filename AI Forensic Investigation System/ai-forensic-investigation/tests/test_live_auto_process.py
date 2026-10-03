"""CCTV auto-processing supervisor tests.

Hermetic: no cv2, no RTSP stream and no YOLO are touched. A fake source
factory supplies deterministic sources; persistence uses the shared test DB
(SQLite, same file the app's ``SessionLocal`` points at) so the supervisor's
own ``SessionLocal`` writes are observable through the ``db`` fixture.

The supervisor background thread is never started here except in one explicit
thread test; everything else drives ``poll()`` directly for determinism.
"""

import time

import pytest

from app.database.models import Camera
from app.live.auto_process import AutoProcessSupervisor
from app.live.manager import manager

# RFC 5737 TEST-NET-3: never routable, so nothing here can open a real stream.
URL = "rtsp://203.0.113.55:554/stream"


def _health(alive=True, running=True, opened=True, error=None, restarts=0, last_frame_at=None):
    return {
        "alive": alive,
        "running": running,
        "opened": opened,
        "error": error,
        "restarts": restarts,
        "last_frame_at": last_frame_at if last_frame_at is not None else time.time(),
        "source": "rtsp",
    }


class FakeSource:
    def __init__(self, runtime, camera):
        self.runtime = runtime
        self.camera = camera
        self.on_finished = None
        self.started = False
        self.stopped = False
        self.start_error = None
        self._health = _health()

    def start(self):
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    def stop(self):
        self.stopped = True

    def health(self):
        return dict(self._health)

    def set_health(self, **kw):
        self._health.update(kw)


@pytest.fixture
def supervisor(db):
    """An enabled supervisor wired to a fake source factory + shared DB."""
    sup = AutoProcessSupervisor(
        manager,
        enabled=True,
        poll_seconds=0.05,
        min_restart_interval=0.0,
        run_detection=False,
        source_factory=lambda runtime, camera: FakeSource(runtime, camera),
    )
    yield sup
    sup.stop()


@pytest.fixture
def camera(db):
    row = Camera(camera_name="Front Gate", auto_process=True, rtsp_url=URL)
    db.add(row)
    db.commit()
    db.refresh(row)
    yield row
    manager.clear()
    db.query(Camera).filter(Camera.id == row.id).delete()
    db.commit()


def _fresh(sup):
    return sup.poll()


# ------------------------------------------------------------------- basics


def test_disabled_supervisor_is_a_noop(db):
    sup = AutoProcessSupervisor(manager, enabled=False)
    try:
        assert sup.poll()["scanned"] == 0
    finally:
        sup.stop()


def test_poll_returns_summary(supervisor, camera):
    summary = _fresh(supervisor)
    assert summary["started"] == 1
    assert summary["scanned"] == 1
    assert summary["kept"] == 0
    assert summary["stopped"] == 0


def test_creates_rtsp_session_for_auto_process_camera(supervisor, camera):
    _fresh(supervisor)
    runtime = manager.get(camera.id)
    assert runtime is not None
    assert runtime.transport == "rtsp"
    assert runtime.status.value == "LIVE"
    assert runtime.camera_source is not None
    assert runtime.camera_source.started is True


def test_persists_online_health(supervisor, camera, db):
    _fresh(supervisor)
    db.refresh(camera)
    assert camera.health_status == "ONLINE"
    assert camera.last_seen_at is not None
    assert camera.last_error is None
    assert camera.reconnect_attempts == 0


def test_keeps_existing_session_and_refreshes_health(supervisor, camera, db):
    _fresh(supervisor)
    runtime = manager.get(camera.id)
    source = runtime.camera_source
    source.set_health(alive=False, running=True, opened=True, error="stale")
    summary = _fresh(supervisor)
    db.refresh(camera)
    assert summary["kept"] == 1
    assert summary["started"] == 0
    assert camera.health_status == "RECONNECTING"
    assert camera.last_error == "stale"


# ------------------------------------------------------------------- edge


def test_camera_without_url_stays_offline(supervisor, db):
    row = Camera(camera_name="No URL", auto_process=True, rtsp_url=None)
    db.add(row)
    db.commit()
    try:
        summary = _fresh(supervisor)
        assert summary["started"] == 0
        assert manager.get(row.id) is None
        db.refresh(row)
        assert row.health_status == "OFFLINE"
        assert row.last_error == "no RTSP URL configured"
    finally:
        manager.clear()
        db.query(Camera).filter(Camera.id == row.id).delete()
        db.commit()


def test_failed_source_is_stopped_and_marked_error(supervisor, camera, db, monkeypatch):
    def broken_factory(runtime, cam):
        src = FakeSource(runtime, cam)
        src.start_error = RuntimeError("stream refused")
        return src

    monkeypatch.setattr(supervisor, "_source_factory", broken_factory)
    summary = _fresh(supervisor)
    db.refresh(camera)
    assert summary["started"] == 0
    assert manager.get(camera.id) is None
    assert camera.health_status == "ERROR"
    assert "stream refused" in (camera.last_error or "")


def test_cleared_flag_stops_supervised_session(supervisor, camera, db):
    _fresh(supervisor)
    assert manager.get(camera.id) is not None
    camera.auto_process = False
    db.commit()
    summary = _fresh(supervisor)
    assert summary["stopped"] == 1
    assert manager.get(camera.id) is None


def test_restart_floor_prevents_hot_loop(supervisor, camera, db):
    _fresh(supervisor)
    manager.stop(camera.id)  # simulate the source gave up
    supervisor._owned.pop(camera.id, None)
    supervisor._min_restart_interval = 10.0
    with supervisor._lock:
        supervisor._owned[camera.id] = supervisor._clock()
    summary = _fresh(supervisor)
    db.refresh(camera)
    assert summary["started"] == 0
    assert camera.health_status == "OFFLINE"
    assert "restart interval" in (camera.last_error or "")


def test_cold_restart_after_source_end(supervisor, camera, db):
    """A camera whose source ended is cold-restarted on the next poll."""
    _fresh(supervisor)
    runtime = manager.get(camera.id)
    runtime.camera_source.set_health(alive=False, running=False, opened=False, error="gave up")
    runtime.camera_source.on_finished()
    assert manager.get(camera.id) is None
    summary = _fresh(supervisor)
    db.refresh(camera)
    assert summary["started"] >= 1
    assert manager.get(camera.id) is not None
    assert camera.health_status == "ONLINE"


# ------------------------------------------------------------------- thread


def test_thread_reconciles_and_stops(supervisor, camera):
    supervisor.start()
    assert supervisor.running is True
    deadline = time.time() + 2.0
    while manager.get(camera.id) is None and time.time() < deadline:
        time.sleep(0.02)
    assert manager.get(camera.id) is not None
    supervisor.stop()
    assert supervisor.running is False


def test_thread_does_not_start_when_disabled(camera):
    sup = AutoProcessSupervisor(
        manager,
        enabled=False,
        poll_seconds=0.05,
        source_factory=lambda runtime, cam: FakeSource(runtime, cam),
    )
    try:
        sup.start()
        time.sleep(0.15)
        assert manager.get(camera.id) is None
    finally:
        sup.stop()
        manager.clear()