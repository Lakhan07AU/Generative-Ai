"""Phase 4 integration tests: VLM wired into the live session manager.

Covers: VLM lifecycle on the session state machine, tracking-event -> evidence
selection -> observation production, the WebSocket stream + RBAC +
unsubscribe-on-disconnect, manual REST analyze, config disable, provider-failure
resilience (session stays live), session isolation, and stop/cleanup.

No real camera, network or VLM provider is involved; provider mode is the
deterministic simulation so output is fully grounded in test metadata.
"""

import time

import numpy as np
import pytest

from app.ai import provider
from app.core.config import settings
from app.detection.schemas import BoundingBox, DetectionFrame, DetectionObject
from app.live.manager import SessionStatus, manager
import app.detection.pipeline as pipeline_mod
from detection_fakes import FakeEngine


def create_camera(client, headers, name="P4-CAM"):
    res = client.post(
        "/cameras",
        headers=headers,
        json={"camera_name": name, "location": "P4 scene", "camera_type": "MOBILE"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def wait_for(predicate, timeout=6.0, step=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


@pytest.fixture
def detected(monkeypatch):
    """Enable detection globally for these tests and share one fake engine."""
    shared = FakeEngine(detections_per_call=[1, 1, 1])
    monkeypatch.setattr(settings, "YOLO_DETECTION_ENABLED", True)
    monkeypatch.setattr(pipeline_mod, "get_engine", lambda *a, **k: shared)
    return shared


@pytest.fixture
def vlm_config(monkeypatch):
    """Enable VLM for tests with tight rate limits so sequences are fast."""
    monkeypatch.setattr(settings, "VLM_ENABLED", True)
    monkeypatch.setattr(settings, "VLM_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(settings, "VLM_MAX_REQUESTS_PER_SESSION", 200)
    monkeypatch.setattr(settings, "VLM_EVENT_TRIGGERS",
                        "object_entered,object_stopped,object_reappeared,prolonged_presence,object_exited")
    monkeypatch.setattr(settings, "VLM_RETRIES", 0)
    monkeypatch.setattr(settings, "VLM_RETRY_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr(settings, "VLM_MAX_FRAMES_PER_REQUEST", 3)


def _np_frame(value=64):
    return np.full((240, 320, 3), value, dtype=np.uint8)


def _det_frame(frame_id, ts, n=1):
    dets = [
        DetectionObject(
            detection_id=f"d-{frame_id}-{i}",
            class_id=0,
            class_name="person",
            confidence=0.9,
            bbox=BoundingBox(x1=10, y1=10 + i * 40, x2=110, y2=110 + i * 40),
            frame_timestamp=ts,
            session_id=7,
            frame_id=frame_id,
            camera_id=3,
            frame_width=320,
            frame_height=240,
        )
        for i in range(n)
    ]
    return DetectionFrame(
        session_id=7,
        camera_id=3,
        frame_id=frame_id,
        frame_timestamp=ts,
        frame_width=320,
        frame_height=240,
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


def _seed_buffer(runtime, n=5, t0=None, value=64):
    t0 = t0 if t0 is not None else time.time() - 2.0
    for i in range(n):
        runtime.buffer.append(_np_frame(value), t0 + i)
    return t0


def _trigger_object_entered(runtime, t0):
    """Feed overlapping detections so tracking emits object_entered events."""
    for i in (1, 2, 3):
        runtime._on_detection_result(_det_frame(i, t0 + i))


# ------------------------------------------------------- lifecycle


def test_vlm_starts_with_detection_and_stops(client, auth_headers, detected, vlm_config):
    cam = create_camera(client, auth_headers, "P4-LIFE")
    runtime = _start_sim(client, auth_headers, cam["id"], "P4-LIFE")
    runtime.mark_live()
    assert runtime.vlm_session is not None
    assert runtime.vlm_session.running
    runtime.stop()
    assert runtime.vlm_session is None
    assert runtime.status in (SessionStatus.COMPLETED, SessionStatus.ERROR)


def test_vlm_disabled_by_config(client, auth_headers, detected, vlm_config, monkeypatch):
    monkeypatch.setattr(settings, "VLM_ENABLED", False)
    cam = create_camera(client, auth_headers, "P4-DIS")
    runtime = _start_sim(client, auth_headers, cam["id"], "P4-DIS")
    runtime.mark_live()
    assert runtime.vlm_session is None
    snap = runtime.snapshot()
    assert snap["vlm_enabled"] is False
    # REST analyze reports the disable cleanly.
    res = client.post(f"/live/cameras/{cam['id']}/vlm/analyze", headers=auth_headers, json={"trigger": "manual"})
    assert res.status_code == 409
    assert "disabled" in res.json()["detail"].lower()
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


# ------------------------------------------------------- event-driven


def test_tracking_event_triggers_observation(client, auth_headers, detected, vlm_config):
    cam = create_camera(client, auth_headers, "P4-EVENT")
    runtime = _start_sim(client, auth_headers, cam["id"], "P4-EVENT")
    runtime.mark_live()
    t0 = _seed_buffer(runtime)
    _trigger_object_entered(runtime, t0)

    assert wait_for(lambda: runtime.vlm_session.recent_observations())
    obs = runtime.vlm_session.recent_observations()[0]
    assert obs["type"] == "vlm_observation"
    assert obs["trigger"] == "event"
    assert obs["session_id"] == runtime.session_db_id
    assert obs["camera_id"] == cam["id"]
    assert obs["source_frames"], "observation must reference real evidence frames"
    assert all(it["classification"] in ("OBSERVED", "INFERRED", "UNKNOWN") for it in obs["items"])
    assert obs["provider_mode"] == "simulation"
    snap = runtime.snapshot()
    assert snap["vlm_observations"] >= 1
    assert snap["vlm_requests"] >= 1
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_non_trigger_events_do_not_enqueue(client, auth_headers, detected, vlm_config, monkeypatch):
    monkeypatch.setattr(settings, "VLM_EVENT_TRIGGERS", "object_stopped")
    cam = create_camera(client, auth_headers, "P4-NOTRIG")
    runtime = _start_sim(client, auth_headers, cam["id"], "P4-NOTRIG")
    runtime.mark_live()
    t0 = _seed_buffer(runtime)
    _trigger_object_entered(runtime, t0)  # object_entered NOT in trigger set
    time.sleep(0.5)
    assert runtime.vlm_session.recent_observations() == []
    assert runtime.vlm_session.snapshot()["vlm_requests"] == 0
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


# ------------------------------------------------------- manual REST


def test_manual_analyze_queues_and_produces_observation(client, auth_headers, detected, vlm_config):
    cam = create_camera(client, auth_headers, "P4-MANUAL")
    runtime = _start_sim(client, auth_headers, cam["id"], "P4-MANUAL")
    runtime.mark_live()
    _seed_buffer(runtime, value=80)

    res = client.post(f"/live/cameras/{cam['id']}/vlm/analyze", headers=auth_headers, json={"trigger": "manual"})
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["status"] == "queued"
    assert body["request_id"]

    assert wait_for(lambda: runtime.vlm_session.recent_observations())
    obs = runtime.vlm_session.recent_observations()[0]
    assert obs["trigger"] == "manual"
    assert obs["request_id"] == body["request_id"]
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_manual_analyze_requires_live_roles(client, auth_headers, reviewer_headers, detected, vlm_config):
    cam = create_camera(client, auth_headers, "P4-RBAC")
    runtime = _start_sim(client, auth_headers, cam["id"], "P4-RBAC")
    runtime.mark_live()
    res = client.post(f"/live/cameras/{cam['id']}/vlm/analyze", headers=reviewer_headers, json={"trigger": "manual"})
    assert res.status_code in (401, 403)
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_manual_analyze_no_active_session(client, auth_headers, detected, vlm_config):
    res = client.post("/live/cameras/99999/vlm/analyze", headers=auth_headers, json={"trigger": "manual"})
    assert res.status_code == 404


def test_manual_analyze_invalid_trigger(client, auth_headers, detected, vlm_config):
    cam = create_camera(client, auth_headers, "P4-BADTG")
    runtime = _start_sim(client, auth_headers, cam["id"], "P4-BADTG")
    runtime.mark_live()
    res = client.post(f"/live/cameras/{cam['id']}/vlm/analyze", headers=auth_headers, json={"trigger": "nonsense"})
    assert res.status_code == 422
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


# ------------------------------------------------------- WebSocket


def test_vlm_ws_streams_request_and_observation(client, auth_headers, detected, vlm_config):
    cam = create_camera(client, auth_headers, "P4-WS")
    token = auth_headers["Authorization"].split(" ")[1]
    runtime = _start_sim(client, auth_headers, cam["id"], "P4-WS")
    runtime.mark_live()
    t0 = _seed_buffer(runtime)

    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/vlm") as ws:
        ws.send_json({"type": "auth", "token": token})
        m1 = ws.receive_json()
        assert m1["type"] == "auth_ok"
        m2 = ws.receive_json()
        assert m2["type"] == "vlm_status"
        assert m2["vlm_enabled"] is True

        _trigger_object_entered(runtime, t0)
        seen_request = False
        seen_observation = False
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and not (seen_request and seen_observation):
            msg = ws.receive_json()
            if msg["type"] == "vlm_request":
                seen_request = True
            elif msg["type"] == "vlm_observation":
                seen_observation = True
                assert msg["camera_id"] == cam["id"]
                assert msg["source_frames"]
                assert msg["provider_mode"] in ("simulation", "openai")
        assert seen_request
        assert seen_observation

    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_vlm_ws_unsubscribes_on_disconnect(client, auth_headers, detected, vlm_config):
    cam = create_camera(client, auth_headers, "P4-UNSUB")
    token = auth_headers["Authorization"].split(" ")[1]
    runtime = _start_sim(client, auth_headers, cam["id"], "P4-UNSUB")
    runtime.mark_live()

    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/vlm") as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.receive_json()
        assert len(runtime._vlm_subscribers) == 1

    assert wait_for(lambda: len(runtime._vlm_subscribers) == 0)
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_vlm_ws_rejects_reviewer(client, auth_headers, reviewer_headers, detected, vlm_config):
    cam = create_camera(client, auth_headers, "P4-WS-RBAC")
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/vlm") as ws:
        ws.send_json({"type": "auth", "token": reviewer_headers["Authorization"].split(" ")[1]})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Insufficient permissions" in msg["detail"]
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


# ------------------------------------------------------- resilience + isolation


def test_vlm_provider_failure_survives_session(client, auth_headers, detected, vlm_config, monkeypatch):
    def _boom(*a, **k):
        raise provider.ProviderError("VLM backend unavailable")

    monkeypatch.setattr(provider, "vision_observe_frames", _boom)
    cam = create_camera(client, auth_headers, "P4-ERR")
    token = auth_headers["Authorization"].split(" ")[1]
    runtime = _start_sim(client, auth_headers, cam["id"], "P4-ERR")
    runtime.mark_live()
    t0 = _seed_buffer(runtime)

    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/vlm") as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.receive_json()
        ws.receive_json()
        _trigger_object_entered(runtime, t0)
        seen_error = False
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and not seen_error:
            msg = ws.receive_json()
            if msg["type"] == "vlm_error":
                seen_error = True
                assert "VLM backend unavailable" in msg["detail"]
        assert seen_error

    # Session keeps running after a provider failure.
    assert runtime.status == SessionStatus.LIVE
    assert runtime.vlm_session is not None and runtime.vlm_session.running
    assert runtime.vlm_error is None  # per-job failures are not session errors
    snap = runtime.snapshot()
    assert snap["vlm_enabled"] is True
    assert snap["vlm_observations"] == 0
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_vlm_session_isolation_two_cameras(client, auth_headers, detected, vlm_config):
    cam_a = create_camera(client, auth_headers, "P4-ISO-A")
    cam_b = create_camera(client, auth_headers, "P4-ISO-B")
    rt_a = _start_sim(client, auth_headers, cam_a["id"], "P4-ISO-A")
    rt_b = _start_sim(client, auth_headers, cam_b["id"], "P4-ISO-B")
    rt_a.mark_live()
    rt_b.mark_live()

    assert rt_a.vlm_session is not None and rt_b.vlm_session is not None
    assert rt_a.vlm_session is not rt_b.vlm_session

    ta = _seed_buffer(rt_a, value=50)
    _trigger_object_entered(rt_a, ta)
    assert wait_for(lambda: rt_a.vlm_session.recent_observations())
    assert rt_b.vlm_session.recent_observations() == []
    assert rt_b.vlm_session.snapshot()["vlm_requests"] == 0

    client.post(f"/live/cameras/{cam_a['id']}/stop", headers=auth_headers)
    client.post(f"/live/cameras/{cam_b['id']}/stop", headers=auth_headers)


def test_vlm_worker_cleanup_on_stop(client, auth_headers, detected, vlm_config):
    cam = create_camera(client, auth_headers, "P4-CLEAN")
    runtime = _start_sim(client, auth_headers, cam["id"], "P4-CLEAN")
    runtime.mark_live()
    worker = runtime.vlm_session._worker
    assert worker is not None and worker.running
    runtime.stop()
    assert not worker.running
    assert runtime.vlm_session is None