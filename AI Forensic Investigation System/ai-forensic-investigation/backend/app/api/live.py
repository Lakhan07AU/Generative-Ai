"""Phase 1 live camera API: REST control + WebSocket signaling/status.

Transport design (per Phase 1 requirements):
  * Mobile camera media travels over WebRTC (aiortc receives the peer track).
    No REST/base64 frame upload is used for media transport.
  * SDP offer/answer + ICE trickling happen on a dedicated signaling WebSocket,
    kept separate from frame processing.
  * Session state is exposed in real time on a status WebSocket.
"""

import asyncio
import logging
import os
from functools import partial
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database.models import Camera, CameraSession, User
from app.schemas.live import CameraSessionOut, LiveStartRequest, LiveStatusOut, VlmAnalyzeRequest
from app.auth.deps import get_current_user, require_roles
from app.auth.security import decode_access_token
from app.audit.service import record_audit
from app.live.manager import SessionStatus, manager
from app.live.synthetic import FrameSimulationFeeder
from app.live.usb_camera import UsbCameraSource
from app.live.video_feeder import VideoFileFeeder

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])

LIVE_ROLES = ("ADMIN", "SECURITY_OFFICER", "INVESTIGATOR")


# ------------------------------------------------------------- HTTP helpers


def _camera_session_out(runtime) -> CameraSessionOut:
    return CameraSessionOut(
        id=runtime.session_db_id or 0,
        camera_id=runtime.camera_id,
        status=runtime.status.value,
        transport=runtime.transport,
        fps_target=runtime.fps_target,
        started_by_user_id=runtime.started_by_user_id,
        error=runtime.error,
        frames_received=runtime.ingestion.received,
        frames_sampled=runtime.ingestion.sampled,
        frames_buffered=runtime.buffer.count(),
    )


def _start_runtime(
    db: Session,
    camera: Camera,
    user: User,
    payload: LiveStartRequest,
) -> "object":
    """Create a DB row + in-memory runtime and move it to CONNECTING."""
    from app.live.manager import ActiveSessionError

    try:
        runtime = manager.start(
            camera_id=camera.id,
            camera_name=camera.camera_name,
            started_by_user_id=user.id,
            transport=payload.transport or "webrtc",
            fps_target=payload.fps_target,
            window_seconds=payload.buffer_window_seconds,
            max_frames=payload.buffer_max_frames,
        )
    except ActiveSessionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    row = CameraSession(
        camera_id=camera.id,
        status=SessionStatus.CREATED.value,
        transport=payload.transport or "webrtc",
        fps_target=runtime.fps_target,
        started_by_user_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    runtime.session_db_id = row.id
    runtime.begin()
    record_audit(
        db,
        "live_session_start",
        user_id=user.id,
        entity_type="camera",
        entity_id=camera.id,
        details=f"camera_id={camera.id} transport={runtime.transport} fps_target={runtime.fps_target}",
    )
    return runtime


def _on_file_finished(runtime):
    try:
        runtime.stop()
    except Exception:
        pass


def _on_source_finished(runtime):
    """USB/DroidCam source thread ended (device unplugged or gave up)."""
    try:
        source = getattr(runtime, "camera_source", None)
        if source is not None:
            source.stop()
            runtime.camera_source = None
        if runtime.status in SessionStatus.active_values():
            runtime.mark_error("USB/DroidCam capture ended")
        runtime.stop()
        manager.stop(runtime.camera_id)
    except Exception:
        pass


# ------------------------------------------------------------------- REST


@router.post(
    "/live/cameras/{camera_id}/start",
    response_model=CameraSessionOut,
    status_code=status.HTTP_201_CREATED,
)
def start_live_camera(
    camera_id: int,
    payload: LiveStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    transport = payload.transport or "webrtc"
    if transport not in ("webrtc", "simulation", "file", "droidcam_usb"):
        raise HTTPException(status_code=422, detail=f"Unsupported transport: {transport}")
    runtime = _start_runtime(db, camera, current_user, payload)
    if transport == "simulation":
        runtime.simulation = FrameSimulationFeeder(runtime)
        runtime.simulation.start()
        runtime.mark_live()
    if transport == "file":
        if not payload.video_path:
            raise HTTPException(status_code=422, detail="video_path is required for file transport")
        # Security: resolve and verify path is under DEMO_DATA_DIR
        from app.core.config import settings
        video_path = os.path.realpath(payload.video_path)
        demo_dir = os.path.realpath(settings.DEMO_DATA_DIR)
        if not video_path.startswith(demo_dir + os.sep) and not video_path.startswith(demo_dir):
            raise HTTPException(status_code=403, detail="video_path must be under the demo dataset directory")
        if not os.path.isfile(video_path):
            raise HTTPException(status_code=404, detail=f"Video file not found: {os.path.basename(video_path)}")
        feeder = VideoFileFeeder(runtime, video_path, fps_target=payload.fps_target)
        feeder.on_finished = lambda: _on_file_finished(runtime)
        runtime.video_feeder = feeder
        feeder.start()
        runtime.mark_live()
    if transport == "droidcam_usb":
        usb = UsbCameraSource(
            runtime,
            device_index=payload.device_index,
            fps_target=payload.fps_target,
        )
        usb.on_finished = lambda: _on_source_finished(runtime)
        try:
            usb.start()
        except Exception as exc:  # noqa: BLE001 - device/OpenCV failure
            runtime.mark_error(f"USB/DroidCam capture failed: {exc}")
            manager.stop(camera.id)
            raise HTTPException(status_code=503, detail=f"USB/DroidCam camera unavailable: {exc}")
        runtime.camera_source = usb
        runtime.mark_live()
    return _camera_session_out(runtime)


@router.post("/live/cameras/{camera_id}/stop", response_model=CameraSessionOut)
def stop_live_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    runtime = manager.get(camera_id)
    if runtime is None:
        raise HTTPException(status_code=409, detail="No active live session for this camera")
    if getattr(runtime, "simulation", None) is not None:
        runtime.simulation.stop()
        runtime.simulation = None
    if getattr(runtime, "video_feeder", None) is not None:
        runtime.video_feeder.stop()
        runtime.video_feeder = None
    if getattr(runtime, "camera_source", None) is not None:
        runtime.camera_source.stop()
        runtime.camera_source = None
    runtime.stop()  # STOPPING -> COMPLETED (persisted)
    manager.stop(camera_id)  # release the single-session lock
    record_audit(
        db,
        "live_session_stop",
        user_id=current_user.id,
        entity_type="camera",
        entity_id=camera_id,
        details=f"camera_id={camera_id} session_id={runtime.session_db_id}",
    )
    return _camera_session_out(runtime)


@router.get("/live/cameras/{camera_id}/status", response_model=LiveStatusOut)
def live_status(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    runtime = manager.get(camera_id)
    if runtime is None:
        return LiveStatusOut(
            camera_id=camera.id,
            camera_name=camera.camera_name,
            active=False,
            status="OFFLINE",
        )
    data = runtime.snapshot()
    return LiveStatusOut(**data)


@router.get("/live/sessions", response_model=list[LiveStatusOut])
def live_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return [LiveStatusOut(**r.snapshot()) for r in manager.active_sessions()]


# --------------------------------------------------------- WebSocket auth


def _user_from_token(db: Session, token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    payload = decode_access_token(token)
    if payload is None or not payload.get("sub"):
        return None
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        return None
    return user


async def _ws_authenticate(websocket: WebSocket, db: Session, require_roles_any: tuple) -> Optional[User]:
    """Read the mandatory first ``auth`` message and validate the JWT."""
    try:
        msg = await websocket.receive_json()
    except (ValueError, RuntimeError):
        await websocket.close(code=1008, reason="Invalid signaling message")
        return None
    if msg.get("type") != "auth":
        await websocket.send_json({"type": "error", "detail": "First message must be 'auth'"})
        await websocket.close(code=1008, reason="Missing auth message")
        return None
    user = _user_from_token(db, msg.get("token"))
    if user is None:
        await websocket.send_json({"type": "error", "detail": "Invalid or expired token"})
        await websocket.close(code=1008, reason="Authentication failed")
        return None
    if require_roles_any and user.role not in require_roles_any:
        await websocket.send_json({"type": "error", "detail": "Insufficient permissions"})
        await websocket.close(code=1008, reason="Insufficient permissions")
        return None
    return user


# ------------------------------------------------------- WebSocket signaling


def _ensure_webrtc(runtime, candidate_sender=None) -> None:
    if getattr(runtime, "webrtc", None) is not None:
        # Re-point the candidate relay at the newest signaling socket so a
        # reconnecting phone keeps receiving the server's ICE candidates.
        if candidate_sender is not None:
            runtime.webrtc._on_ice_candidate = candidate_sender
        return
    from app.live.webrtc import LiveWebRTCConnection, WebRTCNotAvailable

    try:
        runtime.webrtc = LiveWebRTCConnection(
            on_frame=lambda frame, ts: runtime.ingest_frame(frame, ts),
            on_error=lambda exc: runtime.mark_error(str(exc)),
            on_state_change=lambda state: _on_pc_state(runtime, state),
            on_ice_candidate=candidate_sender or (lambda _payload: None),
        )
    except WebRTCNotAvailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _on_pc_state(runtime, state: str) -> None:
    if state == "connected":
        runtime.mark_live()
    elif state == "failed":
        runtime.mark_error("WebRTC connection failed")
    elif state in ("disconnected", "closed"):
        if runtime.status in SessionStatus.active_values():
            runtime.transition("DISCONNECTED")


async def _close_webrtc(runtime) -> None:
    webrtc = getattr(runtime, "webrtc", None)
    runtime.webrtc = None
    if webrtc is not None:
        # Suppress connection-state callbacks during teardown: closing the PC
        # fires connectionstatechange("closed") which must NOT flip the session
        # to DISCONNECTED. Genuine mid-session failures still propagate because
        # we only silence the state callback for this deliberate close.
        webrtc._on_state_change = lambda _state: None
        try:
            await webrtc.close()
        except Exception:  # noqa: BLE001
            pass


@router.websocket("/live/cameras/{camera_id}/ws/signaling")
async def ws_live_signaling(websocket: WebSocket, camera_id: int, db: Session = Depends(get_db)):
    await websocket.accept()
    runtime = None
    owns_session = False  # True only when THIS socket created the runtime
    try:
        user = await _ws_authenticate(websocket, db, require_roles_any=LIVE_ROLES)
        if user is None:
            return
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if camera is None:
            await websocket.send_json({"type": "error", "detail": "Camera not found"})
            await websocket.close(code=1004, reason="Camera not found")
            return

        runtime = manager.get(camera_id)
        if runtime is not None and runtime.status not in SessionStatus.active_values():
            # A stale terminal-state runtime (e.g. a WebRTC session that failed
            # or a feeder/source that ended) must be evicted so a reconnecting
            # phone gets a fresh session instead of an endless "Session not
            # active" rejection. REST /start already overwrites via
            # manager.start(); the signaling path must do the same.
            manager.stop(camera_id)
            runtime = None
        if runtime is None:
            from app.live.manager import ActiveSessionError

            try:
                runtime = manager.start(camera_id=camera_id, camera_name=camera.camera_name, started_by_user_id=user.id, transport="webrtc")
                owns_session = True
                row = CameraSession(camera_id=camera_id, status=SessionStatus.CREATED.value, transport="webrtc", fps_target=runtime.fps_target, started_by_user_id=user.id)
                db.add(row)
                db.commit()
                db.refresh(row)
                runtime.session_db_id = row.id
                runtime.begin()
            except ActiveSessionError as exc:
                owns_session = False
                await websocket.send_json({"type": "error", "detail": str(exc)})
                await websocket.close(code=1013, reason="Session conflict")
                return

        def _send_candidate(payload: dict) -> None:
            # aiortc fires the ICE handler on the event loop; schedule the
            # websocket send so we never await from within the callback.
            asyncio.ensure_future(
                websocket.send_json(
                    {
                        "type": "trickle",
                        "camera_id": camera_id,
                        "session_id": runtime.session_db_id,
                        "candidate": payload,
                    }
                )
            )

        try:
            _ensure_webrtc(runtime, candidate_sender=_send_candidate)
        except HTTPException as exc:
            if owns_session and manager.get(camera_id) is runtime:
                manager.stop(camera_id)
            await websocket.send_json({"type": "error", "detail": exc.detail})
            await websocket.close(code=1011, reason=str(exc.detail))
            return

        await websocket.send_json({
            "type": "auth_ok",
            "camera_id": camera_id,
            "session_id": runtime.session_db_id,
            "status": runtime.status.value,
            "transport": runtime.transport,
        })

        while True:
            try:
                msg = await websocket.receive_json()
            except ValueError:
                await websocket.send_json({"type": "error", "detail": "Malformed JSON"})
                continue

            mtype = msg.get("type")
            if mtype == "offer":
                sdp = msg.get("sdp", "")
                if runtime.status not in SessionStatus.active_values():
                    await websocket.send_json({"type": "error", "detail": "Session not active"})
                    continue
                try:
                    if runtime.webrtc is None:
                        _ensure_webrtc(runtime)
                    answer_sdp = await runtime.webrtc.handle_offer(sdp)
                    await websocket.send_json({
                        "type": "answer",
                        "camera_id": camera_id,
                        "session_id": runtime.session_db_id,
                        "sdp": answer_sdp,
                    })
                except Exception as exc:  # noqa: BLE001
                    runtime.mark_error(f"WebRTC offer failed: {exc}")
                    await websocket.send_json({"type": "error", "detail": "Failed to negotiate WebRTC offer"})
                    await _close_webrtc(runtime)
            elif mtype == "trickle":
                payload = msg.get("candidate") or msg
                try:
                    runtime.webrtc.add_ice_candidate(payload)
                    await websocket.send_json({"type": "trickle_ack", "camera_id": camera_id})
                except Exception as exc:  # noqa: BLE001
                    await websocket.send_json({"type": "error", "detail": f"Invalid ICE candidate: {exc}"})
            elif mtype == "bye":
                runtime.stop()
                await websocket.send_json({"type": "bye_ack", "camera_id": camera_id})
                break
            elif mtype == "ping":
                await websocket.send_json({"type": "pong", "camera_id": camera_id})
            else:
                await websocket.send_json({"type": "error", "detail": f"Unknown message type: {mtype}"})
    except WebSocketDisconnect:
        # Peer went away without "bye": only an OWNING socket kills the session.
        # An unrelated signaling socket attached to a REST-managed session must
        # not tear it down.
        if (
            runtime is not None
            and owns_session
            and runtime.status in SessionStatus.active_values()
        ):
            runtime.transition("DISCONNECTED")
    finally:
        if runtime is not None:
            await _close_webrtc(runtime)
            # Only clean up the session this socket created/owns. An unrelated
            # signaling socket attached to a REST-managed session must NOT stop it.
            if owns_session and manager.get(camera_id) is runtime:
                manager.stop(camera_id)


# ------------------------------------------------------------- WebSocket status


@router.websocket("/live/cameras/{camera_id}/ws/status")
async def ws_live_status(websocket: WebSocket, camera_id: int, db: Session = Depends(get_db)):
    await websocket.accept()
    user = await _ws_authenticate(websocket, db, require_roles_any=())
    if user is None:
        return
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        await websocket.send_json({"type": "error", "detail": "Camera not found"})
        await websocket.close(code=1004, reason="Camera not found")
        return

    runtime = manager.get(camera_id)
    sub = runtime.subscribe() if runtime is not None else None
    queue = sub.queue if sub is not None else asyncio.Queue()
    try:
        await websocket.send_json({"type": "auth_ok", "camera_id": camera_id})
        await websocket.send_json(
            {"type": "status", **runtime.snapshot()} if runtime is not None
            else {"type": "status", "camera_id": camera_id, "camera_name": camera.camera_name, "active": False, "status": "OFFLINE"}
        )
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                await websocket.send_json(payload)
            except asyncio.TimeoutError:
                if runtime is not None:
                    await websocket.send_json({"type": "status", **runtime.snapshot()})
    except WebSocketDisconnect:
        pass
    finally:
        if sub is not None:
            runtime.unsubscribe(sub)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------- WebSocket detection


@router.websocket("/live/cameras/{camera_id}/ws/detections")
async def ws_live_detections(websocket: WebSocket, camera_id: int, db: Session = Depends(get_db)):
    """Phase 2: per-session YOLO detection stream.

    Frames are broadcast as ``{"type": "detection", ...}`` with absolute-pixel
    bounding boxes when objects are found, plus ``has_detection: false`` frames
    every processed second. The payload is the :class:`DetectionFrame` broadcast
    dict (see ``app/detection/schemas.py``).
    """
    await websocket.accept()
    user = await _ws_authenticate(websocket, db, require_roles_any=LIVE_ROLES)
    if user is None:
        return
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        await websocket.send_json({"type": "error", "detail": "Camera not found"})
        await websocket.close(code=1004, reason="Camera not found")
        return

    runtime = manager.get(camera_id)
    sub = runtime.subscribe_detection() if runtime is not None else None
    queue = sub.queue if sub is not None else asyncio.Queue()
    try:
        await websocket.send_json({"type": "auth_ok", "camera_id": camera_id})
        if runtime is not None:
            snap = runtime.snapshot()
            await websocket.send_json({
                "type": "detection_status",
                "camera_id": camera_id,
                "detection_enabled": snap["detection_enabled"],
                "detection_error": snap["detection_error"],
                "detection_metrics": snap["detection_metrics"],
                "recent": runtime.detection.recent_results(limit=20) if runtime.detection else [],
            })
        else:
            await websocket.send_json({
                "type": "detection_status",
                "camera_id": camera_id,
                "detection_enabled": False,
                "recent": [],
            })
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                await websocket.send_json(payload)
            except asyncio.TimeoutError:
                if runtime is not None:
                    await websocket.send_json({
                        "type": "detection_keepalive",
                        "camera_id": camera_id,
                        "detection_enabled": runtime.detection is not None,
                    })
    except WebSocketDisconnect:
        pass
    finally:
        if sub is not None:
            runtime.unsubscribe_detection(sub)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------- WebSocket tracking


@router.websocket("/live/cameras/{camera_id}/ws/tracking")
async def ws_live_tracking(websocket: WebSocket, camera_id: int, db: Session = Depends(get_db)):
    """Phase 3: per-session multi-object tracking stream.

    Broadcasts ``{"type": "track_update", ...}`` messages as tracks persist
    across frames, plus ``{"type": "tracking_metrics", ...}`` aggregate
    snapshots. All spatial coordinates are ABSOLUTE FRAME PIXELS (documented).
    No facial recognition, name identification, or biometric identification.
    """
    await websocket.accept()
    user = await _ws_authenticate(websocket, db, require_roles_any=LIVE_ROLES)
    if user is None:
        return
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        await websocket.send_json({"type": "error", "detail": "Camera not found"})
        await websocket.close(code=1004, reason="Camera not found")
        return

    runtime = manager.get(camera_id)
    sub = runtime.subscribe_tracking() if runtime is not None else None
    queue = sub.queue if sub is not None else asyncio.Queue()
    try:
        await websocket.send_json({"type": "auth_ok", "camera_id": camera_id})
        if runtime is not None:
            snap = runtime.snapshot()
            await websocket.send_json({
                "type": "tracking_status",
                "camera_id": camera_id,
                "tracking_enabled": snap.get("tracking_enabled", False),
                "active_tracks": snap.get("active_tracks", 0),
                "total_events": snap.get("total_events", 0),
            })
        else:
            await websocket.send_json({
                "type": "tracking_status",
                "camera_id": camera_id,
                "tracking_enabled": False,
                "active_tracks": 0,
                "total_events": 0,
            })
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                await websocket.send_json(payload)
            except asyncio.TimeoutError:
                if runtime is not None:
                    await websocket.send_json({
                        "type": "tracking_keepalive",
                        "camera_id": camera_id,
                        "tracking_enabled": runtime.tracking is not None,
                    })
    except WebSocketDisconnect:
        pass
    finally:
        if sub is not None:
            runtime.unsubscribe_tracking(sub)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------- VLM (Phase 4)


@router.post(
    "/live/cameras/{camera_id}/vlm/analyze",
    status_code=status.HTTP_202_ACCEPTED,
)
def vlm_manual_analyze(
    camera_id: int,
    payload: Optional[VlmAnalyzeRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    """Queue a manual VLM observation of the current evidence buffer.

    The response only carries the request id; the result arrives on the
    ``/ws/vlm`` stream as ``vlm_observation``. No client-supplied timestamps are
    accepted - evidence windows are always derived from server-side buffers.
    """
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    runtime = manager.get(camera_id)
    if runtime is None:
        raise HTTPException(status_code=409, detail="No active live session for this camera")
    vlm = getattr(runtime, "vlm_session", None)
    if vlm is None or not vlm.running:
        raise HTTPException(
            status_code=409,
            detail=(
                "VLM analysis is disabled for this session"
                if not getattr(runtime, "vlm_session", None)
                else "VLM worker not ready"
            ),
        )
    trigger = (payload.trigger if payload else "manual").strip().lower()
    if trigger not in ("manual", "event"):
        raise HTTPException(status_code=422, detail=f"Unsupported trigger: {trigger}")
    request_id = vlm.manual_analyze()
    if request_id is None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="VLM rate limit reached or no evidence frames available",
        )
    record_audit(
        db,
        "vlm_analyze",
        user_id=current_user.id,
        entity_type="camera",
        entity_id=camera_id,
        details=f"camera_id={camera_id} session_id={runtime.session_db_id} request_id={request_id}",
    )
    return {
        "camera_id": camera_id,
        "session_id": runtime.session_db_id,
        "request_id": request_id,
        "status": "queued",
    }


@router.websocket("/live/cameras/{camera_id}/ws/vlm")
async def ws_live_vlm(websocket: WebSocket, camera_id: int, db: Session = Depends(get_db)):
    """Phase 4: per-session VLM observation stream.

    Broadcasts ``vlm_request`` (a request was accepted), ``vlm_observation``
    (grounded result), ``vlm_error`` (provider failure - session stays live),
    ``vlm_metrics`` and ``vlm_keepalive``. Observations always carry full
    provenance (camera/session/source frame refs) and never pixel data.
    """
    await websocket.accept()
    user = await _ws_authenticate(websocket, db, require_roles_any=LIVE_ROLES)
    if user is None:
        return
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        await websocket.send_json({"type": "error", "detail": "Camera not found"})
        await websocket.close(code=1004, reason="Camera not found")
        return

    runtime = manager.get(camera_id)
    sub = runtime.subscribe_vlm() if runtime is not None else None
    queue = sub.queue if sub is not None else asyncio.Queue()
    try:
        await websocket.send_json({"type": "auth_ok", "camera_id": camera_id})
        if runtime is not None:
            snap = runtime.snapshot()
            recent = (
                runtime.vlm_session.recent_observations(limit=20)
                if runtime.vlm_session is not None
                else []
            )
            await websocket.send_json({
                "type": "vlm_status",
                "camera_id": camera_id,
                "vlm_enabled": snap.get("vlm_enabled", False),
                "vlm_last_error": snap.get("vlm_last_error"),
                "vlm_requests": snap.get("vlm_requests", 0),
                "vlm_observations": snap.get("vlm_observations", 0),
                "recent": recent,
            })
        else:
            await websocket.send_json({
                "type": "vlm_status",
                "camera_id": camera_id,
                "vlm_enabled": False,
                "recent": [],
            })
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                await websocket.send_json(payload)
            except asyncio.TimeoutError:
                if runtime is not None:
                    await websocket.send_json({
                        "type": "vlm_keepalive",
                        "camera_id": camera_id,
                        "vlm_enabled": runtime.vlm_session is not None and runtime.vlm_session.running,
                    })
    except WebSocketDisconnect:
        pass
    finally:
        if sub is not None:
            runtime.unsubscribe_vlm(sub)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass