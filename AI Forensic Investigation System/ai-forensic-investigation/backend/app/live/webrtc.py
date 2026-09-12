"""WebRTC receive transport for live mobile cameras (Phase 1).

Uses aiortc to receive a peer video track (mobile browser acts as the sender)
and pushes decoded BGR frames into the live ingest pipeline. SDP exchange and
ICE trickling happen over the app's signaling WebSocket (see
``app/api/live.py``); no REST/base64 frame upload is used for media transport.
"""

import asyncio
import json
import logging
import time
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

try:  # aiortc is an optional dependency for live ingest
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.sdp import candidate_from_sdp
    import aiortc

    WEBRTC_AVAILABLE: bool = True
except Exception as exc:  # pragma: no cover - environment dependent
    aiortc = None
    RTCPeerConnection = None
    RTCSessionDescription = None
    candidate_from_sdp = None
    WEBRTC_AVAILABLE = False
    _IMPORT_ERROR = exc


FrameCallback = Callable[[object, float], None]
ErrorCallback = Callable[[Exception], None]
IceCandidateCallback = Callable[[dict], None]


def _default_ice_servers() -> list:
    """Read the WEBRTC_ICE_SERVERS JSON list (e.g. STUN/TURN) from settings.

    Empty by default: host-candidate-only is enough for the same-LAN physical
    demo. Set e.g. ``[{"urls": ["stun:stun.l.google.com:19302"]}]`` when the
    phone and backend are separated by NAT.
    """
    try:
        from app.core.config import settings

        raw = getattr(settings, "WEBRTC_ICE_SERVERS", "[]")
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except Exception:  # noqa: BLE001 - config must never break signaling
        logger.warning("WEBRTC_ICE_SERVERS is not valid JSON: falling back to no ICE servers")
    return []


def _ice_configuration() -> object:
    """Return an aiortc ``RTCConfiguration`` built from ``WEBRTC_ICE_SERVERS``.

    The JSON value is a list of RTCIceServer dicts with ``urls`` (string or
    list) plus optional ``username`` / ``credential``. Falls back to ``None``
    (aiortc default, host candidates only) when the list is empty.
    """
    try:
        from aiortc import RTCConfiguration, RTCIceServer

        servers = []
        for entry in _default_ice_servers():
            if not isinstance(entry, dict) or not entry.get("urls"):
                continue
            servers.append(
                RTCIceServer(
                    urls=entry["urls"],
                    username=entry.get("username"),
                    credential=entry.get("credential"),
                )
            )
        if not servers:
            return None
        return RTCConfiguration(iceServers=servers)
    except Exception:  # noqa: BLE001 - ICE misconfig must never break signaling
        logger.warning("Could not build ICE configuration from WEBRTC_ICE_SERVERS")
        return None


class WebRTCNotAvailable(RuntimeError):
    """Raised when aiortc (or its backend) is not importable on this host."""


class LiveWebRTCConnection:
    """A single receive-only RTCPeerConnection bound to a live session.

    ``on_frame(frame, timestamp)`` is invoked for every decoded video frame and
    ``on_error(exc)`` for transport failures. The connection is passive: the
    remote peer (mobile browser) sends the offer.
    """

    def __init__(
        self,
        on_frame: FrameCallback,
        on_error: Optional[ErrorCallback] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
        on_ice_candidate: Optional[IceCandidateCallback] = None,
    ) -> None:
        if not WEBRTC_AVAILABLE:
            raise WebRTCNotAvailable("aiortc is not installed on this host")
        self._on_frame = on_frame
        self._on_error = on_error or (lambda _exc: None)
        self._on_state_change = on_state_change or (lambda _state: None)
        self._on_ice_candidate = on_ice_candidate or (lambda _payload: None)
        self._receiver_task: Optional[asyncio.Task] = None
        self._closed = False
        self.pc = RTCPeerConnection(_ice_configuration())
        # ICE candidates are buffered until the remote offer is applied so that
        # candidates arriving before the offer never raise spurious errors.
        self._pending_candidates: List[object] = []
        self._remote_applied = False

        @self.pc.on("track")
        def _on_track(track) -> None:  # type: ignore[misc]
            if track.kind != "video":
                return
            if self._receiver_task is None or self._receiver_task.done():
                self._receiver_task = asyncio.ensure_future(self._receiver_loop(track))

        @self.pc.on("icecandidate")
        def _on_ice_candidate(candidate) -> None:  # type: ignore[misc]
            # Forward the server's own ICE candidates to the signaling socket so
            # the mobile peer can complete connectivity checks (trickle-ICE).
            if candidate is None:
                return
            payload = {
                "candidate": candidate.candidate or "",
                "sdpMid": candidate.sdpMid,
                "sdpMLineIndex": candidate.sdpMLineIndex or 0,
            }
            # Candidates may fire after a deliberate close; suppress them then.
            if not self._closed:
                self._on_ice_candidate(payload)

        @self.pc.on("connectionstatechange")
        def _on_connection_state() -> None:  # type: ignore[misc]
            self._on_state_change(self.pc.connectionState)

    # -------------------------------------------------------------- control

    async def handle_offer(self, sdp: str) -> str:
        """Consume a remote offer and return the local answer SDP.

        Buffered ICE candidates (received via ``add_ice_candidate`` before the
        offer) are flushed once the remote description has been applied.
        """
        self._assert_open()
        await self.pc.setRemoteDescription(RTCSessionDescription(type="offer", sdp=sdp))
        self._remote_applied = True
        self._flush_pending_candidates()
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        # Re-serialize local description AFTER setLocalDescription: aiortc 1.x
        # inlines the freshly gathered ICE candidates into the SDP strings only
        # once the description is applied, so the pre-gather ``answer.sdp`` is
        # candidate-less and mobile peers could never complete connectivity.
        if self.pc.localDescription is None or self.pc.localDescription.sdp is None:
            return ""
        return self.pc.localDescription.sdp

    def add_ice_candidate(self, candidate_payload: dict) -> None:
        """Add an ICE candidate; buffers it until the remote description is set.

        The candidate is parsed eagerly so malformed payloads still raise an
        ``InvalidICE candidate`` error at trickle time - only *ordering* is
        made harmless by buffering.
        """
        self._assert_open()
        candidate = candidate_from_sdp(candidate_payload.get("candidate", ""))
        candidate.sdpMid = candidate_payload.get("sdpMid")
        candidate.sdpMLineIndex = int(candidate_payload.get("sdpMLineIndex", 0))
        if self._remote_applied:
            asyncio.ensure_future(self.pc.addIceCandidate(candidate))
        else:
            self._pending_candidates.append(candidate)

    def _flush_pending_candidates(self) -> None:
        pending = self._pending_candidates
        self._pending_candidates = []
        for candidate in pending:
            try:
                asyncio.ensure_future(self.pc.addIceCandidate(candidate))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Flushed ICE candidate failed: %s", exc)

    def _assert_open(self) -> None:
        if self._closed:
            raise RuntimeError("WebRTC connection is already closed")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pending_candidates.clear()
        if self._receiver_task is not None:
            self._receiver_task.cancel()
        await self.pc.close()

    # ------------------------------------------------------------ receiver

    async def _receiver_loop(self, track) -> None:
        try:
            while True:
                frame = await track.recv()
                if frame is None:
                    break
                try:
                    ndarray = frame.to_ndarray(format="bgr24")
                except Exception as exc:  # decode problem -> signal, keep going
                    logger.warning("Live frame decode failed: %s", exc)
                    continue
                self._on_frame(ndarray, time.time())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not self._closed:
                self._on_error(exc)


def webrtc_available() -> bool:
    return WEBRTC_AVAILABLE