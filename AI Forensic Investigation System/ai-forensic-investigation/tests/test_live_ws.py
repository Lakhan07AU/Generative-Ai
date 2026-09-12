"""Phase 1 WebSocket tests: signaling auth/RBAC + status push."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.live.manager import manager


def create_camera(client, headers, name="WS-CAM"):
    res = client.post(
        "/cameras",
        headers=headers,
        json={"camera_name": name, "location": "WS scene", "camera_type": "MOBILE"},
    )
    assert res.status_code == 201, res.text
    return res.json()


# ------------------------------------------------------------ signaling


def test_signaling_rejects_invalid_token(client):
    # token validation happens before any camera lookup
    with client.websocket_connect("/live/cameras/424242/ws/signaling") as ws:
        ws.send_json({"type": "auth", "token": "not-a-real-token"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "token" in msg["detail"].lower()
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_signaling_auth_ok_flow(client, auth_headers):
    cam = create_camera(client, auth_headers, "WS-SIGNAL")
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/signaling") as ws:
        ws.send_json({"type": "auth", "token": auth_headers["Authorization"].split(" ")[1]})
        msg = ws.receive_json()
        assert msg["type"] == "auth_ok"
        assert msg["camera_id"] == cam["id"]
        assert msg["status"] in ("CONNECTING", "LIVE")
        ws.send_json({"type": "bye"})
        bye = ws.receive_json()
        assert bye["type"] == "bye_ack"


def test_signaling_role_forbidden(client, auth_headers, reviewer_headers):
    cam = create_camera(client, auth_headers, "WS-VIEW")
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/signaling") as ws:
        ws.send_json({"type": "auth", "token": reviewer_headers["Authorization"].split(" ")[1]})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Insufficient permissions" in msg["detail"]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_signaling_missing_camera_error(client, auth_headers):
    with client.websocket_connect("/live/cameras/404040/ws/signaling") as ws:
        ws.send_json({"type": "auth", "token": auth_headers["Authorization"].split(" ")[1]})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Camera not found" in msg["detail"]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_signaling_bad_offer_reports_error(client, auth_headers):
    cam = create_camera(client, auth_headers, "WS-OFFER")
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/signaling") as ws:
        ws.send_json({"type": "auth", "token": auth_headers["Authorization"].split(" ")[1]})
        msg = ws.receive_json()
        assert msg["type"] == "auth_ok"
        ws.send_json({"type": "offer", "sdp": "v=0\r\nm=video 0 UDP/TLS/RTP/SAVPF 96\r\ninvalid"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "WebRTC" in err.get("detail", "")


# ----------------------------------------------------------------- status


def test_status_ws_requires_valid_auth(client):
    with client.websocket_connect("/live/cameras/434343/ws/status") as ws:
        ws.send_json({"type": "auth", "token": "garbage"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_status_ws_pushes_transitions(client, auth_headers):
    cam = create_camera(client, auth_headers, "WS-STATUS")
    token = auth_headers["Authorization"].split(" ")[1]

    start = client.post(
        f"/live/cameras/{cam['id']}/start", headers=auth_headers, json={"transport": "simulation"}
    )
    assert start.status_code == 201, start.text
    runtime = manager.get(cam["id"])
    assert runtime is not None
    runtime.mark_live()

    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/status") as ws:
        ws.send_json({"type": "auth", "token": token})
        m1 = ws.receive_json()
        assert m1["type"] == "auth_ok"
        m2 = ws.receive_json()
        assert m2["type"] == "status"
        assert m2["status"] == "LIVE"
        assert m2["camera_id"] == cam["id"]

        runtime.transition("STOPPING")
        m3 = ws.receive_json()
        assert m3["type"] == "status"
        assert m3["status"] == "STOPPING"

    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_status_ws_offline_when_no_session(client, auth_headers):
    cam = create_camera(client, auth_headers, "WS-OFF")
    token = auth_headers["Authorization"].split(" ")[1]
    with client.websocket_connect(f"/live/cameras/{cam['id']}/ws/status") as ws:
        ws.send_json({"type": "auth", "token": token})
        m1 = ws.receive_json()
        assert m1["type"] == "auth_ok"
        m2 = ws.receive_json()
        assert m2["type"] == "status"
        assert m2["active"] is False
        assert m2["status"] == "OFFLINE"