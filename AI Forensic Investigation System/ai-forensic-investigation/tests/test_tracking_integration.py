"""Phase 3 integration tests: tracking wired into the live session manager.

Covers: tracking lifecycle on the session state machine, the detection->tracking
seam (DetectionObject/dict normalisation), tracking WebSocket stream + RBAC +
unsubscribe-on-disconnect, tracking metrics surfaced in live status, config
disable, and session isolation.

No real camera/device is involved; all input frames are synthetic.
"""

import time

import numpy as np
import pytest

from app.core.config import settings
from app.detection.schemas import BoundingBox, DetectionFrame, DetectionObject
from app.live.manager import SessionStatus, manager
import app.detection.pipeline as pipeline_mod
from detection_fakes import FakeEngine


def create_camera(client, headers, name="P3-CAM"):
    res = client.post(
        "/cameras",
        headers=headers,
        json={"camera_name": name, "location": "P3 scene", "camera_type": "MOBILE"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def wait_for(predicate, timeout=5.0, step=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


@pytest.fixture
def detected(monkeypatch):
    """Enable detection globally for this test and share one fake engine."""
    shared = FakeEngine(detections_per_call=[1, 1, 1])
    monkeypatch.setattr(settings, "YOLO_DETECTION_ENABLED", True)
    monkeypatch.setattr(pipeline_mod, "get_engine", lambda *a, **k: shared)
    return shared


def _det_frame(frame_id, ts, n=1, x=10, y=10, w=100, h=100):
    dets = [
        DetectionObject(
            detection_id=f"d-{frame_id}-{i}",
            class_id=0,
            class_name="person",
            confidence=0.9,
            bbox=BoundingBox(x1=x, y1=y + i * 20, x2=x + w, y2=y + h + i * 20),
            frame_timestamp=ts,
            session_id=7,
            frame_id=frame_id,
            camera_id=3,
            frame_width=640,
            frame_height=480,
        )
        for i in range(n)
    ]
    return DetectionFrame(
        session_id=7,
        camera_id=3,
        frame_id=frame_id,
        frame_timestamp=ts,
        frame_width=640,
        frame_height=480,
        detections=dets,
    )


def _start_sim(client, headers, cam_id, name):
    start = client.post(
        f"/live/cameras/{cam_id}/start", headers=headers, json={"transport": "simulation"}
    )
    assert start.status_code == 201, start.text
    runtime = manager.get(cam_id)
    runtime.simulation.stop()
    runtime.simulation = None
    return runtime


# ------------------------------------------------------- lifecycle + metrics


def test_tracking_starts_with_detection_and_stops(client, auth_headers, detected):
    cam = create_camera(client, auth_headers, "P3-LIFE")
    runtime = manager.start(
        camera_id=cam["id"], camera_name=cam["camera_name"],
        started_by_user_id=1, transport="simulation",
    )
    runtime.begin()
    assert runtime.tracking is None
    runtime.mark_live()
    assert runtime.tracking is not None
    assert runtime.tracking.camera_id == str(cam["id"])

    runtime.stop()
    assert runtime.tracking is None
    assert runtime.status == SessionStatus.COMPLETED


def test_tracking_metrics_flow_through_status(client, auth_headers):
    cam = create_camera(client, auth_headers, "P3-METRIC")
    runtime = _start_sim(client, auth_headers, cam["id"], "P3-METRIC")
    runtime.mark_live()
    runtime.start_tracking()
    assert runtime.tracking is not None

    # Feed three overlapping person detections -> one persistent track.
    for i in range(3):
        runtime._on_detection_result(_det_frame(i, 1_000.0 + i * 1.0))
    assert wait_for(lambda: runtime.tracking.tracks())

    res = client.get(f"/live/cameras/{cam['id']}/status", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["tracking_enabled"] is True
    assert body["active_tracks"] == 1
    assert body["total_events"] >= 0

    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_tracking_disabled_by_config(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "TRACKING_ENABLED", False)
    cam = create_camera(client, auth_headers, "P3-DIS")
    runtime = _start_sim(client, auth_headers, cam["id"], "P3-DIS")
    runtime.mark_live()
    assert runtime.tracking is None
    snap = runtime.snapshot()
    assert snap["tracking_enabled"] is False
    assert snap["active_tracks"] == 0
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_session_isolation_two_cameras(client, auth_headers, detected):
    cam_a = create_camera(client, auth_headers, "P3-ISO-A")
    cam_b = create_camera(client, auth_headers, "P3-ISO-B")
    rt_a = _start_sim(client, auth_headers, cam_a["id"], "P3-ISO-A")
    rt_b = _start_sim(client, auth_headers, cam_b["id"], "P3-ISO-B")
    rt_a.mark_live()
    rt_b.mark_live()

    assert rt_a.tracking is not None and rt_b.tracking is not None
    assert rt_a.tracking is not rt_b.tracking
    assert rt_a.tracking.camera_id != rt_b.tracking.camera_id

    for i in range(3):
        rt_a._on_detection_result(_det_frame(i, 2_000.0 + i * 1.0))
    assert wait_for(lambda: rt_a.tracking.tracks())
    assert rt_b.tracking.tracks() == []

    client.post(f"/live/cameras/{cam_a['id']}/stop", headers=auth_headers)
    client.post(f"/live/cameras/{cam_b['id']}/stop", headers=auth_headers)


# ------------------------------------------------- tracing the detection seam


def test_normalize_detections_converts_objects_and_dicts(monkeypatch):
    from app.live.manager import LiveSessionRuntime

    monkeypatch.setattr(settings, "TRACKING_ENABLED", True)
    rt = LiveSessionRuntime(camera_id=1, camera_name="x", started_by_user_id=1)
    rt.start_tracking()

    obj = DetectionObject(
        detection_id="d",
        class_id=0,
        class_name="person",
        confidence=0.8,
        bbox=BoundingBox(x1=5, y1=6, x2=55, y2=66),
        frame_timestamp=1.0,
    )
    d = {"label": "car", "confidence": 0.7, "bbox": [1, 2, 11, 22]}
    normalized = rt._normalize_detections([obj, d])
    assert normalized[0] == {"label": "person", "confidence": 0.8, "bbox": [5, 6, 55, 66]}
    assert normalized[1] == {"label": "car", "confidence": 0.7, "bbox": [1, 2, 11, 22]}
    rt.stop_tracking()


def test_feed_tracking_produces_tracks_and_metrics(client, auth_headers):
    cam = create_camera(client, auth_headers, "P3-SEAM")
    runtime = manager.start(
        camera_id=cam["id"], camera_name=cam["camera_name"],
        started_by_user_id=1, transport="simulation",
    )
    runtime.begin()
    runtime.mark_live()
    runtime.start_tracking()
    assert runtime.tracking is not None

    snap_before = runtime.tracking.snapshot()
    for i in range(3):
        runtime._on_detection_result(_det_frame(i, 3_000.0 + i * 1.0))

    assert wait_for(lambda: len(runtime.tracking.tracks()) == 1)
    snap = runtime.tracking.snapshot()
    assert snap["total_updates"] >= snap_before["total_updates"] + 3
    assert snap["active_tracks"] == 1
    assert snap["type"] == "tracking_metrics"
    assert snap["session_id"] == str(runtime.session_db_id or "")
    assert snap["camera_id"] == str(cam["id"])

    runtime.stop()


# ---------------------------------------------------------- WebSocket stream


def test_tracking_ws_streams_updates(client, auth_headers, detected):
    cam = create_camera(client, auth_headers, "P3-WS")
    token = auth_headers["Authorization"].split(" ")[1]
    runtime = _start_sim(client, auth_headers, cam["id"], "P3-WS")
    runtime.mark_live()

    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/tracking") as ws:
        ws.send_json({"type": "auth", "token": token})
        m1 = ws.receive_json()
        assert m1["type"] == "auth_ok"
        m2 = ws.receive_json()
        assert m2["type"] == "tracking_status"
        assert m2["tracking_enabled"] is True

        updates = []
        metrics = []
        deadline = time.monotonic() + 5.0
        for i in range(4):
            runtime._on_detection_result(_det_frame(i, 4_000.0 + i * 1.0))
        while time.monotonic() < deadline and (len(updates) < 3 or len(metrics) < 1):
            msg = ws.receive_json()
            if msg["type"] == "track_update":
                updates.append(msg)
            elif msg["type"] == "tracking_metrics":
                metrics.append(msg)
        assert len(updates) >= 3
        assert len(metrics) >= 1
        first = updates[0]
        assert first["tracking_id"].startswith("Person-")
        assert first["state"] in ("NEW", "ACTIVE", "LOST")
        assert first["bbox"] and len(first["bbox"]) == 4
        assert metrics[-1]["active_tracks"] >= 1

    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_tracking_ws_rejects_reviewer(client, auth_headers, reviewer_headers, detected):
    cam = create_camera(client, auth_headers, "P3-RBAC")
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/tracking") as ws:
        ws.send_json({"type": "auth", "token": reviewer_headers["Authorization"].split(" ")[1]})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Insufficient permissions" in msg["detail"]
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_tracking_ws_unsubscribes_on_disconnect(client, auth_headers):
    cam = create_camera(client, auth_headers, "P3-UNSUB")
    token = auth_headers["Authorization"].split(" ")[1]
    runtime = _start_sim(client, auth_headers, cam["id"], "P3-UNSUB")
    runtime.mark_live()

    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/tracking") as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.receive_json()
        assert len(runtime._tracking_subscribers) == 1

    # websocket context exit -> server must have removed the subscriber
    assert wait_for(lambda: len(runtime._tracking_subscribers) == 0)
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_tracking_ws_on_missing_camera(client, auth_headers):
    token = auth_headers["Authorization"].split(" ")[1]
    with client.websocket_connect("/live/cameras/99999/ws/tracking") as ws:
        ws.send_json({"type": "auth", "token": token})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Camera not found" in msg["detail"]
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()