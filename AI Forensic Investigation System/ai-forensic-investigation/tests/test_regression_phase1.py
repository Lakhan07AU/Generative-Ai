"""Phase 1 regression: pre-existing camera/video/dashboard functionality intact."""

from app.database.models import Camera, CameraSession


def test_camera_create_returns_new_fields(client, auth_headers):
    res = client.post(
        "/cameras",
        headers=auth_headers,
        json={"camera_name": "REG-CAM", "location": "Lobby"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["camera_name"] == "REG-CAM"
    assert body["camera_type"] == "CCTV"      # default backfilled
    assert body["stream_status"] == "OFFLINE"  # default
    assert body["is_live"] is False


def test_camera_create_mobile_type(client, auth_headers):
    res = client.post(
        "/cameras",
        headers=auth_headers,
        json={"camera_name": "REG-MOB", "camera_type": "MOBILE", "stream_source": "mobile-reg-mob"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["camera_type"] == "MOBILE"
    assert body["stream_source"] == "mobile-reg-mob"


def test_camera_list_and_get_still_work(client, auth_headers):
    created = client.post(
        "/cameras", headers=auth_headers, json={"camera_name": "REG-LIST"}
    ).json()
    ls = client.get("/cameras", headers=auth_headers)
    assert ls.status_code == 200
    assert any(c["id"] == created["id"] for c in ls.json())
    got = client.get(f"/cameras/{created['id']}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["camera_name"] == "REG-LIST"


def test_camera_get_missing_still_404(client, auth_headers):
    assert client.get("/cameras/999999", headers=auth_headers).status_code == 404


def test_videos_list_still_works(client, auth_headers):
    res = client.get("/videos", headers=auth_headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_dashboard_still_works(client, auth_headers):
    res = client.get("/dashboard/stats", headers=auth_headers)
    assert res.status_code == 200
    assert "total_videos" in res.json()


def test_live_schema_columns_exist(client, db):
    # Phase 1 added columns/models are part of the schema Base builds
    assert hasattr(Camera, "camera_type")
    assert hasattr(Camera, "is_live")
    assert hasattr(Camera, "stream_status")
    col_names = {c.name for c in Camera.__table__.columns}
    assert {"camera_type", "is_live", "stream_status", "stream_source"} <= col_names
    assert CameraSession.__tablename__ == "camera_sessions"
    assert {c.name for c in CameraSession.__table__.columns} >= {
        "camera_id",
        "status",
        "transport",
        "fps_target",
        "frames_received",
        "frames_sampled",
        "frames_buffered",
    }


def test_phase1_webrtc_flag_exposed(client, auth_headers):
    from app.live.webrtc import webrtc_available, WEBRTC_AVAILABLE

    assert webrtc_available() == WEBRTC_AVAILABLE