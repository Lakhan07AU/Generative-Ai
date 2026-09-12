"""Phase 2 integration & regression tests.

Covers: detection lifecycle on the session state machine, metrics in REST status,
per-session isolation over a shared engine, detection WebSocket (including RBAC),
soft-failure when the model cannot be initialised, and regressions for the three
Phase 1 issues (thread-safe publishing, signaling teardown scoping, ICE ordering).

Detection is wired with :class:`FakeEngine` so no YOLO model is required.
"""

import asyncio
import time

import numpy as np
import pytest

from app.core.config import settings
from app.live.manager import SessionStatus, manager
from app.detection.engine import ModelNotFoundError
import app.detection.pipeline as pipeline_mod
from detection_fakes import FakeEngine


def create_camera(client, headers, name="P2-CAM"):
    res = client.post(
        "/cameras",
        headers=headers,
        json={"camera_name": name, "location": "P2 scene", "camera_type": "MOBILE"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def bgr_frame(w=320, h=240, value=100):
    return np.full((h, w, 3), value, dtype=np.uint8)


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
    shared = FakeEngine(detections_per_call=[5, 2, 0, 3])
    monkeypatch.setattr(settings, "YOLO_DETECTION_ENABLED", True)
    monkeypatch.setattr(pipeline_mod, "get_engine", lambda *a, **k: shared)
    return shared


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


def test_detection_starts_on_live_and_stops_on_stop(client, auth_headers, detected, monkeypatch):
    cam = create_camera(client, auth_headers, "P2-LIFE")
    runtime = manager.start(
        camera_id=cam["id"], camera_name=cam["camera_name"],
        started_by_user_id=1, transport="simulation",
    )
    runtime.begin()
    assert runtime.detection is None
    runtime.mark_live()
    assert runtime.detection is not None and runtime.detection.running
    assert runtime.detection_error is None
    assert runtime.detection.engine is detected  # engine shared from registry

    runtime.stop()
    assert runtime.detection is None
    assert runtime.status == SessionStatus.COMPLETED


def test_detection_metrics_flow_through_status(client, auth_headers, detected):
    cam = create_camera(client, auth_headers, "P2-METRIC")
    runtime = _start_sim(client, auth_headers, cam["id"], "P2-METRIC")
    runtime.mark_live()

    # source -> sampler -> detection (1 s spacing >> sampler interval)
    for i in range(6):
        runtime.ingest_frame(bgr_frame(value=i), timestamp=1_000.0 + i * 1.0)
    assert wait_for(lambda: runtime.detection is not None and
                    runtime.detection.snapshot()["total_processed"] >= 6)

    res = client.get(f"/live/cameras/{cam['id']}/status", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["detection_enabled"] is True
    assert body["detection_error"] is None
    assert body["detection_recent_count"] >= 6
    metrics = body["detection_metrics"]
    assert metrics["total_input"] >= 6
    assert metrics["total_sampled"] >= 6
    assert metrics["total_processed"] >= 6
    assert metrics["total_detections"] > 0

    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_detection_disabled_by_config(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "YOLO_DETECTION_ENABLED", False)
    cam = create_camera(client, auth_headers, "P2-DIS")
    runtime = _start_sim(client, auth_headers, cam["id"], "P2-DIS")
    runtime.mark_live()
    assert runtime.detection is None
    snapshot = runtime.snapshot()
    assert snapshot["detection_enabled"] is False
    assert snapshot["detection_error"] == "Detection disabled by configuration"
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_detection_soft_fails_when_model_unavailable(client, auth_headers, monkeypatch):
    def broken_engine(*a, **k):
        raise ModelNotFoundError("no model here")
    monkeypatch.setattr(settings, "YOLO_DETECTION_ENABLED", True)
    monkeypatch.setattr(pipeline_mod, "get_engine", broken_engine)
    cam = create_camera(client, auth_headers, "P2-SOFT")
    runtime = _start_sim(client, auth_headers, cam["id"], "P2-SOFT")
    runtime.mark_live()
    # Session is still LIVE; detection is unavailable but non-fatal.
    assert runtime.status == SessionStatus.LIVE
    assert runtime.detection is None
    assert "Detection unavailable" in (runtime.detection_error or "")
    # Feeder keeps working - the pipeline never crashes the session.
    runtime.ingest_frame(bgr_frame(), timestamp=5000.0)
    assert runtime.status == SessionStatus.LIVE
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_session_isolation_two_cameras(client, auth_headers, detected):
    cam_a = create_camera(client, auth_headers, "P2-ISO-A")
    cam_b = create_camera(client, auth_headers, "P2-ISO-B")
    rt_a = _start_sim(client, auth_headers, cam_a["id"], "P2-ISO-A")
    rt_b = _start_sim(client, auth_headers, cam_b["id"], "P2-ISO-B")
    rt_a.mark_live()
    rt_b.mark_live()

    assert rt_a.detection is not None and rt_b.detection is not None
    # Shared engine object (loaded once), isolated workers/metrics.
    assert rt_a.detection.engine is rt_b.detection.engine
    assert rt_a.detection.worker is not rt_b.detection.worker
    assert rt_a.detection.metrics is not rt_b.detection.metrics

    for i in range(4):
        rt_a.ingest_frame(bgr_frame(value=i), timestamp=10.0 + i * 1.0)
    assert wait_for(lambda: rt_a.detection.snapshot()["total_processed"] >= 4)
    assert rt_b.detection.snapshot()["total_processed"] == 0

    client.post(f"/live/cameras/{cam_a['id']}/stop", headers=auth_headers)
    client.post(f"/live/cameras/{cam_b['id']}/stop", headers=auth_headers)


# ---------------------------------------------------------- WebSocket stream


def test_detection_ws_streams_results(client, auth_headers, detected):
    cam = create_camera(client, auth_headers, "P2-WS")
    token = auth_headers["Authorization"].split(" ")[1]
    runtime = _start_sim(client, auth_headers, cam["id"], "P2-WS")
    runtime.mark_live()

    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/detections") as ws:
        ws.send_json({"type": "auth", "token": token})
        m1 = ws.receive_json()
        assert m1["type"] == "auth_ok"
        m2 = ws.receive_json()
        assert m2["type"] == "detection_status"
        assert m2["detection_enabled"] is True

        results = []
        for i in range(6):
            runtime.ingest_frame(bgr_frame(value=i), timestamp=2_000.0 + i * 1.0)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and len(results) < 6:
            msg = ws.receive_json()
            if msg["type"] == "detection":
                results.append(msg)
        assert len(results) >= 6
        with_detections = [m for m in results if m["detections"]]
        assert with_detections
        first = with_detections[0]
        assert first["type"] == "detection"
        assert first["camera_id"] == cam["id"]
        assert first["session_id"] == runtime.session_db_id
        for det in first["detections"]:
            x1, y1, x2, y2 = det["bbox"]
            # absolute pixel coordinates, no fractions
            assert all(isinstance(v, int) for v in (x1, y1, x2, y2))
            assert x2 >= x1 and y2 >= y1
            assert 0.0 <= det["confidence"] <= 1.0
            assert det["class_name"]

    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_detection_ws_rejects_reviewer(client, auth_headers, reviewer_headers, detected):
    cam = create_camera(client, auth_headers, "P2-RBAC")
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/detections") as ws:
        ws.send_json({"type": "auth", "token": reviewer_headers["Authorization"].split(" ")[1]})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Insufficient permissions" in msg["detail"]
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_detection_ws_unsubscribes_on_disconnect(client, auth_headers, detected):
    cam = create_camera(client, auth_headers, "P2-UNSUB")
    token = auth_headers["Authorization"].split(" ")[1]
    runtime = _start_sim(client, auth_headers, cam["id"], "P2-UNSUB")
    runtime.mark_live()

    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/detections") as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.receive_json()
        assert len(runtime._detection_subscribers) == 1

    # websocket context exit -> server must have removed the subscriber
    assert wait_for(lambda: len(runtime._detection_subscribers) == 0)
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


# ----------------------------------------------- Phase 1 regression: FIX 1.1


def test_unrelated_signaling_disconnect_keeps_rest_session(client, auth_headers):
    """A REST-started session must survive an unrelated signaling WS closing."""
    cam = create_camera(client, auth_headers, "P2-REST-SURV")
    start = client.post(
        f"/live/cameras/{cam['id']}/start", headers=auth_headers, json={"transport": "simulation"}
    )
    assert start.status_code == 201, start.text
    runtime = manager.get(cam["id"])
    runtime.mark_live()

    token = auth_headers["Authorization"].split(" ")[1]
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/signaling") as ws:
        ws.send_json({"type": "auth", "token": token})
        msg = ws.receive_json()
        assert msg["type"] == "auth_ok"
        assert msg["session_id"] == runtime.session_db_id
    # unrelated signaling connection closed -> REST session MUST stay alive
    assert manager.get(cam["id"]) is runtime
    assert runtime.status == SessionStatus.LIVE

    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_signaling_owned_session_cleaned_up_on_disconnect(client, auth_headers):
    """A session created by a signaling WS must be released when it disconnects."""
    cam = create_camera(client, auth_headers, "P2-SIG-CLEAN")
    token = auth_headers["Authorization"].split(" ")[1]
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/signaling") as ws:
        ws.send_json({"type": "auth", "token": token})
        msg = ws.receive_json()
        assert msg["type"] == "auth_ok"
        runtime = manager.get(cam["id"])
        assert runtime is not None
    # socket closed without "bye" -> session DISCONNECTED + released
    assert wait_for(lambda: manager.get(cam["id"]) is None)
    assert runtime.status == SessionStatus.DISCONNECTED


# ----------------------------------------------- Phase 1 regression: FIX 1.2


@pytest.mark.skipif(not __import__("app.live.webrtc", fromlist=["webrtc_available"]).webrtc_available(),
                    reason="aiortc not installed")
class TestICEBuffering:
    def _conn(self):
        from app.live.webrtc import LiveWebRTCConnection

        return LiveWebRTCConnection(
            on_frame=lambda f, ts: None,
            on_error=lambda exc: None,
        )

    def test_candidate_before_offer_is_buffered(self):
        conn = self._conn()
        payload = {"candidate": "candidate:1 1 udp 2122260223 192.0.2.1 53534 typ host", "sdpMid": "0", "sdpMLineIndex": 0}
        conn.add_ice_candidate(payload)  # must NOT raise before the offer
        conn.add_ice_candidate(payload)
        assert len(conn._pending_candidates) == 2
        assert conn._remote_applied is False

    def test_offer_then_candidates_go_direct_to_pc(self):
        async def scenario():
            conn = self._conn()
            # simulates a completed offer negotiation: afterwards candidates are
            # forwarded immediately instead of buffered
            conn._remote_applied = True
            conn.add_ice_candidate({"candidate": "candidate:1 1 udp 2122260223 192.0.2.5 53534 typ host", "sdpMid": "0", "sdpMLineIndex": 0})
            assert conn._pending_candidates == []

        asyncio.run(scenario())

    def test_multiple_candidates_within_one_session(self):
        conn = self._conn()
        for _ in range(4):
            conn.add_ice_candidate({"candidate": "candidate:2 1 udp 2122260223 192.0.2.2 53534 typ host", "sdpMid": "0", "sdpMLineIndex": 0})
        assert len(conn._pending_candidates) == 4

    def test_invalid_candidate_raises_value_error(self):
        conn = self._conn()
        with pytest.raises(Exception):
            conn.add_ice_candidate({"candidate": "", "sdpMid": "0", "sdpMLineIndex": 0})

    def test_close_clears_buffered_candidates(self):
        conn = self._conn()
        for _ in range(3):
            conn.add_ice_candidate({"candidate": "candidate:1 1 udp 2122260223 192.0.2.3 53534 typ host", "sdpMid": "0", "sdpMLineIndex": 0})
        asyncio.run(conn.close())
        assert conn._pending_candidates == []
        with pytest.raises(RuntimeError):
            conn.add_ice_candidate({"candidate": "candidate:1 1 udp 2122260223 192.0.2.3 53534 typ host", "sdpMid": "0", "sdpMLineIndex": 0})

    def test_offer_flushes_buffered_candidates(self):
        conn = self._conn()
        for i in range(2):
            conn.add_ice_candidate({"candidate": f"candidate:1 1 udp 2122260223 192.0.2.{i} 53534 typ host", "sdpMid": "0", "sdpMLineIndex": 0})
        assert len(conn._pending_candidates) == 2
        conn._remote_applied = True
        conn._flush_pending_candidates()
        assert conn._pending_candidates == []