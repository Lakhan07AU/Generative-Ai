"""Phase 1 live camera REST API tests."""

from app.live.manager import manager
from app.database.models import CameraSession


def create_camera(client, headers, name="LIVE-01"):
    res = client.post(
        "/cameras",
        headers=headers,
        json={"camera_name": name, "location": "Scene A", "camera_type": "MOBILE"},
    )
    assert res.status_code == 201, res.text
    return res.json()


# ------------------------------------------------------------------- auth


def test_start_session_requires_auth(client):
    res = client.post("/live/cameras/1/start", json={"transport": "simulation"})
    assert res.status_code == 401


def test_start_session_rbac_forbidden_for_viewer(client, auth_headers, reviewer_headers):
    cam = create_camera(client, auth_headers, "API-REV-START")
    res = client.post(
        f"/live/cameras/{cam['id']}/start",
        headers=reviewer_headers,
        json={"transport": "simulation"},
    )
    assert res.status_code == 403


def test_stop_session_rbac_forbidden_for_viewer(client, auth_headers, reviewer_headers):
    cam = create_camera(client, auth_headers)
    res = client.post(
        f"/live/cameras/{cam['id']}/stop",
        headers=reviewer_headers,
    )
    assert res.status_code == 403


def test_status_requires_auth(client):
    res = client.get("/live/cameras/1/status")
    assert res.status_code == 401


# ---------------------------------------------------------------- lifecycle


def test_start_missing_camera_404(client, auth_headers):
    res = client.post(
        "/live/cameras/99999/start", headers=auth_headers, json={"transport": "simulation"}
    )
    assert res.status_code == 404


def test_unsupported_transport_422(client, auth_headers):
    cam = create_camera(client, auth_headers, "LIVE-02")
    res = client.post(
        f"/live/cameras/{cam['id']}/start", headers=auth_headers, json={"transport": "rtmp"}
    )
    assert res.status_code == 422


def test_start_stop_status_flow(client, auth_headers):
    cam = create_camera(client, auth_headers, "LIVE-03")
    start = client.post(
        f"/live/cameras/{cam['id']}/start",
        headers=auth_headers,
        json={"transport": "simulation", "fps_target": 5, "buffer_window_seconds": 15, "buffer_max_frames": 150},
    )
    assert start.status_code == 201, start.text
    body = start.json()
    assert body["camera_id"] == cam["id"]
    assert body["transport"] == "simulation"
    assert body["status"] in ("CONNECTING", "LIVE")

    st = client.get(f"/live/cameras/{cam['id']}/status", headers=auth_headers)
    assert st.status_code == 200
    status = st.json()
    assert status["active"] is True
    assert status["camera_id"] == cam["id"]
    assert status["status"] in ("CONNECTING", "LIVE")
    assert status["fps_target"] == 5
    assert status["window_seconds"] == 15

    stop = client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)
    assert stop.status_code == 200, stop.text
    assert stop.json()["status"] == "COMPLETED"

    after = client.get(f"/live/cameras/{cam['id']}/status", headers=auth_headers)
    assert after.status_code == 200
    assert after.json()["active"] is False
    assert after.json()["status"] == "OFFLINE"


def test_start_injects_frames_in_simulation(client, auth_headers):
    cam = create_camera(client, auth_headers, "LIVE-04")
    client.post(
        f"/live/cameras/{cam['id']}/start",
        headers=auth_headers,
        json={"transport": "simulation"},
    )
    import time

    time.sleep(1.2)  # let the synthetic feeder run
    st = client.get(f"/live/cameras/{cam['id']}/status", headers=auth_headers).json()
    assert st["frames_received"] > 0
    assert st["frames_buffered"] > 0
    assert st["frames_sampled"] > 0
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_double_start_conflict_409(client, auth_headers):
    cam = create_camera(client, auth_headers, "LIVE-05")
    first = client.post(
        f"/live/cameras/{cam['id']}/start", headers=auth_headers, json={"transport": "simulation"}
    )
    assert first.status_code == 201
    second = client.post(
        f"/live/cameras/{cam['id']}/start", headers=auth_headers, json={"transport": "simulation"}
    )
    assert second.status_code == 409
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_stop_without_session_409(client, auth_headers):
    cam = create_camera(client, auth_headers, "LIVE-06")
    res = client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)
    assert res.status_code == 409


def test_live_sessions_summary(client, auth_headers):
    cam = create_camera(client, auth_headers, "LIVE-07")
    client.post(
        f"/live/cameras/{cam['id']}/start", headers=auth_headers, json={"transport": "simulation"}
    )
    res = client.get("/live/sessions", headers=auth_headers)
    assert res.status_code == 200
    cameras_in_summary = [s["camera_id"] for s in res.json()]
    assert cam["id"] in cameras_in_summary
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


# ------------------------------------------------------------ persistence


def test_camera_session_row_persisted(client, db, auth_headers):
    cam = create_camera(client, auth_headers, "LIVE-08")
    client.post(
        f"/live/cameras/{cam['id']}/start", headers=auth_headers, json={"transport": "simulation"}
    )
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)
    db.expire_all()
    rows = db.query(CameraSession).filter(CameraSession.camera_id == cam["id"]).all()
    assert len(rows) >= 1
    assert rows[-1].status == "COMPLETED"
    assert rows[-1].transport == "simulation"


def test_camera_live_flags_update(client, auth_headers):
    cam = create_camera(client, auth_headers, "LIVE-09")
    client.post(
        f"/live/cameras/{cam['id']}/start", headers=auth_headers, json={"transport": "simulation"}
    )
    got = client.get(f"/cameras/{cam['id']}", headers=auth_headers).json()
    assert got["is_live"] is True
    assert got["stream_status"] == "LIVE"
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)
    got = client.get(f"/cameras/{cam['id']}", headers=auth_headers).json()
    assert got["is_live"] is False
    assert got["stream_status"] == "OFFLINE"


def test_manager_cleaned_after_stop(client, auth_headers):
    cam = create_camera(client, auth_headers, "LIVE-10")
    client.post(
        f"/live/cameras/{cam['id']}/start", headers=auth_headers, json={"transport": "simulation"}
    )
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)
    assert manager.get(cam["id"]) is None