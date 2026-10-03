"""Browser-preview (MJPEG) tests for backend-owned camera transports.

A ``webcam`` / ``droidcam_usb`` / ``file`` / ``simulation`` session has no video
track in the browser, so the console renders the frames the backend is actually
analysing via ``GET /live/cameras/{id}/stream.mjpg``. Without it the preview is
a black surface while detection still works - which is exactly the bug these
tests pin down.
"""

import io
import sys
import time
import types

import numpy as np
import pytest


def _jpeg_parts(buf: bytes):
    """Extract JPEG bodies from a multipart/x-mixed-replace payload."""
    out, idx = [], 0
    while True:
        head_end = buf.find(b"\r\n\r\n", idx)
        if head_end < 0:
            return out
        head = buf[idx:head_end].decode("latin-1", "replace")
        length = None
        for line in head.splitlines():
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        if length is None:
            return out
        body = buf[head_end + 4:head_end + 4 + length]
        if len(body) == length and body[:2] == b"\xff\xd8":
            out.append(body)
        idx = head_end + 4 + length


# --------------------------------------------------------------------- runtime


def _runtime(camera_id: int, transport: str = "simulation"):
    """A live runtime wired to a source that accepts every frame."""
    from app.live.manager import LiveSessionRuntime, SessionStatus

    rt = LiveSessionRuntime(
        camera_id=camera_id,
        camera_name="preview-test",
        started_by_user_id=None,
        transport=transport,
    )

    class _Source:
        def push_with_ts(self, frame, ts):
            return True

    rt.source = _Source()
    rt._set_status(SessionStatus.LIVE)
    return rt


def test_ingest_publishes_jpeg_only_when_a_preview_client_exists():
    rt = _runtime(9090)
    frame = np.full((48, 64, 3), 128, dtype=np.uint8)

    # No subscriber: the ingest path must not pay for a JPEG encode.
    assert rt._encode_preview(frame) is None

    sub = rt.subscribe_preview()
    try:
        jpeg = rt._encode_preview(frame)
        assert jpeg is not None
        assert jpeg[:2] == b"\xff\xd8", "preview must be a real JPEG"
    finally:
        rt.unsubscribe_preview(sub)

    assert rt._encode_preview(frame) is None, "encode must stop once nobody watches"


def test_ingest_frame_fans_out_encoded_frames_to_preview_subscribers():
    import asyncio

    async def _run():
        rt = _runtime(9091)
        sub = rt.subscribe_preview()  # binds to the running loop
        try:
            assert rt.ingest_frame(np.full((32, 32, 3), 200, dtype=np.uint8), time.time()) is True
            await asyncio.sleep(0)  # let call_soon_threadsafe deliver
            assert not sub.queue.empty()
            return sub.queue.get_nowait()
        finally:
            rt.unsubscribe_preview(sub)

    payload = asyncio.run(_run())
    assert payload[:2] == b"\xff\xd8"


def test_preview_publish_survives_a_missing_loop():
    rt = _runtime(9092)
    sub = rt.subscribe_preview()
    sub.loop = None  # no running loop -> publishing must be a silent no-op
    try:
        rt.ingest_frame(np.zeros((16, 16, 3), dtype=np.uint8), time.time())
    finally:
        rt.unsubscribe_preview(sub)


def test_preview_queue_drops_old_frames_instead_of_growing():
    rt = _runtime(9093)
    sub = rt.subscribe_preview()
    try:
        for i in range(200):
            rt.ingest_frame(np.full((16, 16, 3), i % 255, dtype=np.uint8), time.time())
        assert sub.queue.qsize() <= 64, "a slow client must not grow the queue"
    finally:
        rt.unsubscribe_preview(sub)


# ----------------------------------------------------------------- HTTP layer


@pytest.fixture
def live_camera(client, auth_headers):
    """A real camera row the live endpoints can bind a session to."""
    res = client.post(
        "/cameras",
        headers=auth_headers,
        json={"camera_name": "PREVIEW-CAM", "location": "Bench"},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_stream_requires_authentication(client):
    res = client.get("/live/cameras/1/stream.mjpg")
    assert res.status_code == 401


def test_stream_rejects_an_invalid_token(client):
    res = client.get("/live/cameras/1/stream.mjpg", params={"token": "not-a-real-token"})
    assert res.status_code == 401


def test_stream_requires_an_active_session(client, auth_headers, live_camera):
    token = auth_headers["Authorization"].split()[1]
    res = client.get(f"/live/cameras/{live_camera}/stream.mjpg", params={"token": token})
    assert res.status_code == 409
    assert "active live session" in res.json()["detail"]


def test_stream_requires_live_roles(client, reviewer_headers):
    token = reviewer_headers["Authorization"].split()[1]
    res = client.get("/live/cameras/1/stream.mjpg", params={"token": token})
    assert res.status_code == 403


def test_mjpeg_generator_emits_a_decodable_jpeg_part():
    """The exact bytes an ``<img src=...stream.mjpg>`` receives."""
    import asyncio

    import cv2

    from app.api.live import mjpeg_frame_stream

    async def _run():
        rt = _runtime(9094)
        sub = rt.subscribe_preview()
        agen = mjpeg_frame_stream(rt, sub, "bnd")
        rt.ingest_frame(np.full((40, 60, 3), 77, dtype=np.uint8), time.time())
        await asyncio.sleep(0)  # deliver the published frame
        try:
            return await asyncio.wait_for(agen.__anext__(), timeout=5.0)
        finally:
            await agen.aclose()
            rt.unsubscribe_preview(sub)

    chunk = asyncio.run(_run())
    head, _, rest = chunk.partition(b"\r\n\r\n")
    assert head.startswith(b"--bnd\r\n")
    assert b"Content-Type: image/jpeg" in head
    length = int(head.decode().split("Content-Length:")[1].split("\r\n")[0])
    jpeg = rest[:length]
    assert rest[length:] == b"\r\n"
    assert jpeg[:2] == b"\xff\xd8" and jpeg[-2:] == b"\xff\xd9"
    decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape[0] == 40 and decoded.shape[1] == 60


def test_mjpeg_generator_ends_when_the_session_stops():
    import asyncio

    from app.api.live import mjpeg_frame_stream
    from app.live.manager import SessionStatus

    async def _run():
        rt = _runtime(9095)
        sub = rt.subscribe_preview()
        agen = mjpeg_frame_stream(rt, sub, "bnd")
        rt._set_status(SessionStatus.COMPLETED)
        try:
            # No frames are ever published: the generator must terminate.
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(agen.__anext__(), timeout=5.0)
        finally:
            await agen.aclose()

    asyncio.run(_run())


def test_webrtc_session_is_not_served_as_mjpeg(client, auth_headers, live_camera):
    """A WebRTC session already has a native video track; the preview must 409."""
    from app.live.manager import manager, SessionStatus

    token = auth_headers["Authorization"].split()[1]
    rt = manager.start(
        camera_id=live_camera,
        camera_name="test",
        started_by_user_id=None,
        transport="webrtc",
        fps_target=10,
    )
    try:
        rt._set_status(SessionStatus.LIVE)
        res = client.get(f"/live/cameras/{live_camera}/stream.mjpg", params={"token": token})
        assert res.status_code == 409
        assert "WebRTC" in res.json()["detail"]
    finally:
        manager.stop(live_camera)


# ------------------------------------------------------------ /frame snapshot


def test_latest_preview_stores_and_increments_sequence():
    """Ingesting a frame caches a JPEG; each store bumps the preview sequence."""
    rt = _runtime(9301)
    rt.note_frame_poll()  # a polling client has asked for frames
    rt.ingest_frame(np.full((40, 60, 3), 100, dtype=np.uint8), time.time())
    snap = rt.latest_preview()
    assert snap is not None
    jpeg, seq, epoch = snap
    assert jpeg[:2] == b"\xff\xd8" and jpeg[-2:] == b"\xff\xd9"
    assert seq == rt._preview_seq
    assert seq > 0
    assert epoch > 0
    rt.ingest_frame(np.full((40, 60, 3), 120, dtype=np.uint8), time.time())
    snap2 = rt.latest_preview()
    assert snap2 is not None
    assert snap2[1] > seq, "a newer ingest must produce a newer snapshot"


def test_latest_preview_without_frames_is_none():
    """No encodable frame yet must return None - never a placeholder."""
    rt = _runtime(9302)
    assert rt.latest_preview() is None


def test_frame_poll_keeps_encoding_alive_without_mjpeg_subscribers():
    """note_frame_poll must turn the encoder on even with zero subscribers."""
    import io

    import cv2

    rt = _runtime(9303)
    rt.note_frame_poll()
    rt.ingest_frame(np.full((40, 60, 3), 90, dtype=np.uint8), time.time())
    snap = rt.latest_preview()
    assert snap is not None
    decoded = cv2.imdecode(np.frombuffer(snap[0], dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    # cv2.imwrite of the cached JPEG must round-trip (sanity for the encoder)
    buf = io.BytesIO()
    assert cv2.imencode(".jpg", decoded, [] )[0]
    buf.close()


def test_frame_endpoint_requires_authentication(client):
    res = client.get("/live/cameras/1/frame")
    assert res.status_code == 401


def test_frame_endpoint_rejects_an_invalid_token(client):
    res = client.get("/live/cameras/1/frame", params={"token": "not-a-real-token"})
    assert res.status_code == 401


def test_frame_endpoint_requires_an_active_session(client, auth_headers, live_camera):
    token = auth_headers["Authorization"].split()[1]
    res = client.get(f"/live/cameras/{live_camera}/frame", params={"token": token})
    assert res.status_code == 409
    assert "active live session" in res.json()["detail"]


def test_frame_endpoint_requires_live_roles(client, reviewer_headers):
    token = reviewer_headers["Authorization"].split()[1]
    res = client.get("/live/cameras/1/frame", params={"token": token})
    assert res.status_code == 403


def test_frame_endpoint_serves_the_latest_frame(client, auth_headers, monkeypatch):
    """The endpoint returns the JPEG the detector saw, with sequence headers.

    Mirrors the real poller: the first GET has no frame yet (204) but arms the
    encoder; the next GET, after a frame is ingested, returns the JPEG.
    """
    import cv2

    from app.live.manager import manager, SessionStatus

    token = auth_headers["Authorization"].split()[1]
    rt = manager.start(
        camera_id=9901,
        camera_name="frame-test",
        started_by_user_id=None,
        transport="file",
        fps_target=10,
    )
    try:
        rt._set_status(SessionStatus.LIVE)
        # Poller starts: nothing encodable yet -> 204 and encoder armed.
        res = client.get(f"/live/cameras/9901/frame", params={"token": token})
        assert res.status_code == 204
        rt.ingest_frame(np.full((40, 60, 3), 55, dtype=np.uint8), time.time())
        res = client.get(f"/live/cameras/9901/frame", params={"token": token})
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/jpeg"
        assert int(res.headers["x-frame-sequence"]) > 0
        float(res.headers["x-frame-timestamp"])
        jpeg = res.content
        assert jpeg[:2] == b"\xff\xd8" and jpeg[-2:] == b"\xff\xd9"
        decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded is not None and decoded.shape[0] == 40
    finally:
        manager.stop(9901)

