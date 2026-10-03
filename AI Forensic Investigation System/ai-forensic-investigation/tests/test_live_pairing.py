"""QR camera pairing: single-use, camera+creator-bound device tokens.

Covers:
  * pairing creation (auth, roles, missing camera, audit)
  * QR PNG rendering + ownership/expiry guards
  * signaling WS accepts an unconsumed pairing code
  * signaling WS rejects: unknown / consumed / expired / wrong-camera codes
  * a pairing is consumed exactly once (no replay)
"""

import pytest
from starlette.websockets import WebSocketDisconnect


def create_camera(client, headers, name="PAIR-CAM"):
    res = client.post(
        "/cameras",
        headers=headers,
        json={"camera_name": name, "location": "pairing scene", "camera_type": "MOBILE"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def make_pairing(client, headers, cam_id):
    res = client.post(f"/live/cameras/{cam_id}/pair", headers=headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["camera_id"] == cam_id
    assert len(body["pairing_id"]) >= 32
    assert body["url"].startswith("http")
    assert "/live/mobile" in body["url"]
    qp = dict(x.split("=", 1) for x in body["url"].split("?", 1)[1].split("&"))
    assert qp["camera_id"] == str(cam_id)
    assert qp["pair"] == body["pairing_id"]
    assert "qr_url" in body
    return body


def test_pair_create_requires_live_role(client, auth_headers, reviewer_headers):
    cam = create_camera(client, auth_headers)
    res = client.post(f"/live/cameras/{cam['id']}/pair", headers=reviewer_headers)
    assert res.status_code == 403


def test_pair_create_missing_camera_404(client, auth_headers):
    assert client.post("/live/cameras/999999/pair", headers=auth_headers).status_code == 404


def test_pair_create_and_qr_png(client, auth_headers):
    cam = create_camera(client, auth_headers)
    body = make_pairing(client, auth_headers, cam["id"])
    qr = client.get(f"/live/cameras/{cam['id']}/pair/qr.png?pairing_id={body['pairing_id']}", headers=auth_headers)
    assert qr.status_code == 200
    assert qr.headers["content-type"] == "image/png"
    assert qr.content[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


def test_pair_qr_denies_another_users_pairing(client, auth_headers, admin_headers):
    cam = create_camera(client, auth_headers)
    body = make_pairing(client, auth_headers, cam["id"])
    qr = client.get(f"/live/cameras/{cam['id']}/pair/qr.png?pairing_id={body['pairing_id']}", headers=admin_headers)
    assert qr.status_code == 404


def test_pair_qr_unknown_pairing_404(client, auth_headers):
    cam = create_camera(client, auth_headers)
    qr = client.get(f"/live/cameras/{cam['id']}/pair/qr.png?pairing_id=deadbeefdeadbeef", headers=auth_headers)
    assert qr.status_code == 404


def test_pair_signaling_auth_ok_and_single_use(client, auth_headers):
    cam = create_camera(client, auth_headers)
    body = make_pairing(client, auth_headers, cam["id"])
    pair = body["pairing_id"]

    # First use succeeds.
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/signaling") as ws:
        ws.send_json({"type": "auth", "pair": pair})
        msg = ws.receive_json()
        assert msg["type"] == "auth_ok"
        assert msg["camera_id"] == cam["id"]
        ws.send_json({"type": "bye"})
        assert ws.receive_json()["type"] == "bye_ack"

    # Replay must fail: the token was consumed.
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/signaling") as ws:
        ws.send_json({"type": "auth", "pair": pair})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_pair_signaling_rejects_unknown_code(client, auth_headers):
    cam = create_camera(client, auth_headers)
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/signaling") as ws:
        ws.send_json({"type": "auth", "pair": "missing-pairing-id"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_pair_signaling_rejects_wrong_camera(client, auth_headers):
    cam_a = create_camera(client, auth_headers, "PAIR-A")
    cam_b = create_camera(client, auth_headers, "PAIR-B")
    body = make_pairing(client, auth_headers, cam_a["id"])
    # The URL says camera B, but the pairing belongs to camera A.
    with client.websocket_connect(f"/live/cameras/{cam_b['id']}/ws/signaling") as ws:
        ws.send_json({"type": "auth", "pair": body["pairing_id"]})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_pair_expired_must_consume(client, db, auth_headers):
    from datetime import datetime, timedelta

    from app.database.models import CameraPairing

    cam = create_camera(client, auth_headers)
    body = make_pairing(client, auth_headers, cam["id"])
    row = db.query(CameraPairing).filter(CameraPairing.pairing_id == body["pairing_id"]).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=10)
    db.commit()

    qr = client.get(f"/live/cameras/{cam['id']}/pair/qr.png?pairing_id={body['pairing_id']}", headers=auth_headers)
    assert qr.status_code == 410

    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/signaling") as ws:
        ws.send_json({"type": "auth", "pair": body["pairing_id"]})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_pair_session_attribute_creator(client, auth_headers, db):
    """A paired signaling socket opens the session under the creator identity."""
    from app.database.models import CameraSession

    cam = create_camera(client, auth_headers)
    body = make_pairing(client, auth_headers, cam["id"])
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/signaling") as ws:
        ws.send_json({"type": "auth", "pair": body["pairing_id"]})
        assert ws.receive_json()["type"] == "auth_ok"
        ws.send_json({"type": "bye"})
        assert ws.receive_json()["type"] == "bye_ack"
    row = db.query(CameraSession).filter(CameraSession.camera_id == cam["id"]).first()
    assert row is not None
    assert row.started_by_user_id is not None