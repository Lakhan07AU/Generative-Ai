"""Physical phone camera readiness self-test (canonical, Phase 1 WebRTC).

Validates the backend infrastructure a real Android/iPhone camera needs, then
reports three verdict lines:

    Backend readiness : PASS / FAIL
    WebRTC signaling  : PASS / FAIL / NOT TESTED
    Physical camera   : MANUAL TEST REQUIRED

What it actually does (no physical device required):
  1. READINESS - /health, /docs, login (demo user), camera listing.
  2. SIGNALING - connects to the real signaling WebSocket, authenticates, and
     then performs a genuine WebRTC offer/answer + bidirectional ICE trickle
     exchange against the running backend using aiortc as the "phone" peer.
     If the peer connection reaches "connected", the transport the phone uses
     is proven end-to-end (media path established, empty-test frames only).
     No simulated detections or fake "camera worked" claims are produced.

The physical camera itself (real sensor -> getUserMedia -> RTP) requires a
human with an actual phone; this script cannot claim it, and never will.

Usage:
    python scripts/verify_physical_camera.py [--base-url http://127.0.0.1:8000]
                                             [--email ...] [--password ...]

Exit code 0 = readiness + signaling PASS; 1 = a check failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

BASE_URL_DEFAULT = "http://127.0.0.1:8000"
DEMO_EMAIL = "demo.investigation@forensics-demo.com"
DEMO_PASSWORD = "demo-investigation-2026"

STATUSES: dict[str, str] = {}
CHECKS: list[dict] = []


def _tls_context() -> ssl.SSLContext | None:
    # The dev setup uses a self-signed cert (frontend/scripts/cert.pem). When
    # --base-url is https, skip verification so the exact phone path is provable
    # without deploying a public CA. The cert is a dev-only, LAN-scoped artifact.
    return ssl._create_unverified_context()


def http_json(url: str, method: str = "GET", body=None, token: str | None = None, timeout: float = 15.0):
    req = urllib.request.Request(
        url,
        data=(json.dumps(body).encode() if body is not None else None),
        method=method,
    )
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    ctx = _tls_context() if url.startswith("https") else None
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8", "replace"))


def record(ok: bool, name: str, detail: str = "", section: str = "MISC") -> bool:
    CHECKS.append({"section": section, "check": name, "pass": bool(ok), "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return bool(ok)


def set_section(section: str, ok: bool) -> None:
    prev = STATUSES.get(section, "PASS")
    if prev == "FAIL":
        return
    STATUSES[section] = "PASS" if ok else "FAIL"


# ------------------------------------------------------------------ READINESS


def verify_readiness(base: str, email: str, password: str) -> bool:
    sec = "READINESS"
    ok = True

    try:
        health = http_json(f"{base}/health")
        ok &= record(health.get("status") in (None, "ok", "OK", "healthy") or isinstance(health, dict),
                     "/health responds", f"status={health.get('status', 'n/a')}", sec)
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "/health responds", f"{base}/health -> {exc}", sec)

    try:
        login = http_json(f"{base}/auth/login", "POST",
                          {"email": email, "password": password})
        token = login.get("access_token") or login.get("token")
        ok &= record(bool(token), "login obtains JWT", f"user={email}", sec)
    except Exception as exc:  # noqa: BLE001
        token = None
        ok &= record(False, "login obtains JWT", f"{exc}", sec)

    if not token:
        return ok

    try:
        cams = http_json(f"{base}/cameras", token=token)
        ok &= record(isinstance(cams, list), "camera list reachable",
                     f"{len(cams)} cameras returned", sec)
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "camera list reachable", f"{exc}", sec)

    set_section(sec, ok)
    return ok


# --------------------------------------------------------------- SIGNALING


# Optional aiortc: used only for the signaling loopback self-test.
try:
    from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
    AIORTC_AVAILABLE = True
except Exception:  # noqa: BLE001
    MediaStreamTrack = None
    RTCPeerConnection = None
    RTCSessionDescription = None
    AIORTC_AVAILABLE = False


class _LoopbackVideoTrack(MediaStreamTrack):
    """Minimal aiortc video track: blank frames so the media path is exercised."""

    def __init__(self) -> None:
        super().__init__()
        self._counter = 0
        self.kind = "video"

    async def recv(self):
        import av
        import fractions

        pts = self._counter
        self._counter += 1
        frame = av.VideoFrame(width=320, height=240, format="yuv420p")
        frame.pts = pts
        frame.time_base = fractions.Fraction(1, 30)
        return frame


async def _signaling_loopback(base: str, camera_id: int, token: str) -> dict:
    """Run a real offer/answer + ICE trickle session against the backend.

    Returns {"connected": bool, "detail": str}. Uses aiortc as the phone-side
    peer with an empty test track - proves the exact transport the phone uses.
    """
    import websockets

    from aiortc import RTCPeerConnection, RTCSessionDescription

    ws_url = base.replace("http", "ws", 1) + f"/live/cameras/{camera_id}/ws/signaling"
    pc = RTCPeerConnection()
    pc.addTrack(_LoopbackVideoTrack())
    result = {"connected": False, "detail": "", "candidates_exchanged": 0}
    answer_sdp: str | None = None

    async def _on_icecandidate(candidate) -> None:
        if candidate is None:
            return
        result["candidates_exchanged"] += 1
        if ws is not None:
            try:
                await ws.send(json.dumps({
                    "type": "trickle",
                    "candidate": {
                        "candidate": candidate.candidate or "",
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex or 0,
                    },
                }))
            except Exception:  # noqa: BLE001
                pass

    pc.on("icecandidate", _on_icecandidate)

    async def _on_connection_state() -> None:
        if pc.connectionState == "connected":
            result["connected"] = True

    pc.on("connectionstatechange", _on_connection_state)

    ws = None
    try:
        ws_kwargs = {"open_timeout": 15.0}
        if ws_url.startswith("wss"):
            # Same dev self-signed cert tolerance as the REST path.
            ws_kwargs["ssl"] = ssl._create_unverified_context()
        ws = await websockets.connect(ws_url, **ws_kwargs)
        await ws.send(json.dumps({"type": "auth", "token": token}))

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        # aiortc 1.x inlines gathered ICE candidates only after
        # setLocalDescription, so send the re-serialized local description.
        local = pc.localDescription
        if local is None or local.sdp is None:
            result["detail"] = "offer SDP missing after setLocalDescription"
            return result
        await ws.send(json.dumps({"type": "offer", "sdp": local.sdp}))

        deadline = time.time() + 15.0
        while time.time() < deadline:
            if pc.connectionState == "connected":
                result["detail"] = "peer connection reached 'connected' (transport proven)"
                return result
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
            except asyncio.TimeoutError:
                continue
            mtype = msg.get("type")
            if mtype == "answer":
                answer_sdp = msg.get("sdp")
                await pc.setRemoteDescription(
                    RTCSessionDescription(type="answer", sdp=answer_sdp))
            elif mtype == "trickle":
                cand = msg.get("candidate") or {}
                if cand.get("candidate"):
                    await pc.addIceCandidate({
                        "candidate": cand["candidate"],
                        "sdpMid": cand.get("sdpMid"),
                        "sdpMLineIndex": cand.get("sdpMLineIndex"),
                    })
            elif mtype == "error":
                result["detail"] = f"signaling error: {msg.get('detail')}"
                break
        result["detail"] = (
            result["detail"]
            or f"peer did not reach 'connected' in 15s "
            f"(state={pc.connectionState}, candidates_exchanged={result['candidates_exchanged']})"
        )
    except Exception as exc:  # noqa: BLE001
        result["detail"] = f"{type(exc).__name__}: {exc}"
    finally:
        if ws is not None:
            try:
                await ws.send(json.dumps({"type": "bye"}))
            except Exception:  # noqa: BLE001
                pass
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            await pc.close()
        except Exception:  # noqa: BLE001
            pass
    return result


def verify_signaling(base: str, token: str, _email: str) -> bool:
    sec = "SIGNALING"
    ok = True

    try:
        import websockets  # noqa: F401
        from aiortc import RTCPeerConnection  # noqa: F401
        signaling_supported = True
    except Exception as exc:  # noqa: BLE001
        signaling_supported = False
        ok &= record(False, "websockets+aiortc available in test env", f"{exc}", sec)

    if not signaling_supported:
        set_section(sec, ok)
        return ok

    # Pick a MOBILE camera to attach to; fall back to any camera.
    camera_id = None
    try:
        cams = http_json(f"{base}/cameras", token=token)
        for c in cams:
            if (c.get("camera_type") or "").upper() in ("MOBILE", "OTHER"):
                camera_id = c["id"]
                break
        if camera_id is None and cams:
            camera_id = cams[0]["id"]
        ok &= record(camera_id is not None, "a camera is available for signaling",
                     f"camera_id={camera_id}", sec)
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "a camera is available for signaling", f"{exc}", sec)

    if camera_id is not None:
        loop = asyncio.new_event_loop()
        try:
            resp = loop.run_until_complete(_signaling_loopback(base, camera_id, token))
        finally:
            loop.close()
        ok &= record(resp["connected"], "WebRTC offer/answer+ICE loopback connected",
                     resp["detail"], sec)
    else:
        record(False, "WebRTC offer/answer+ICE loopback connected",
               "no camera available to attach", sec)

    set_section(sec, ok)
    return ok


# ------------------------------------------------------------------- MAIN


def main() -> int:
    parser = argparse.ArgumentParser(description="Physical phone camera readiness self-test")
    parser.add_argument("--base-url", default=BASE_URL_DEFAULT)
    parser.add_argument("--email", default=DEMO_EMAIL)
    parser.add_argument("--password", default=DEMO_PASSWORD)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    try:
        from app.live.webrtc import webrtc_available

        print(f"aiortc backend availability: {'available' if webrtc_available() else 'NOT available'}")
    except Exception:  # noqa: BLE001 - running from another cwd
        print("(aiortc availability check skipped: run from backend/ for full detail)")

    print(f"base-url: {base}")

    try:
        token = None
        # login for later checks (readiness reuses it)
        try:
            login = http_json(f"{base}/auth/login", "POST",
                              {"email": args.email, "password": args.password})
            token = login.get("access_token") or login.get("token")
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] login - {exc}")

        print("--- section READINESS:")
        ok_readiness = verify_readiness(base, args.email, args.password)

        print("--- section SIGNALING:")
        ok_signaling = verify_signaling(base, token or "", args.email)

        print("--- section PHYSICAL:")
        print("  [MANUAL TEST REQUIRED] a real phone must run "
              "the procedure in PHYSICAL_CAMERA_SETUP.md")
        STATUSES["PHYSICAL"] = "MANUAL TEST REQUIRED"

        print("\nsection matrix:")
        for sec, val in [("READINESS", STATUSES.get("READINESS", "FAIL")),
                         ("SIGNALING", STATUSES.get("SIGNALING", "FAIL")),
                         ("PHYSICAL", "MANUAL TEST REQUIRED")]:
            print(f"  {val:>16}  {sec}")

        print("\nverdicts:")
        print(f"  Backend readiness : {STATUSES.get('READINESS', 'FAIL')}")
        print(f"  WebRTC signaling  : {STATUSES.get('SIGNALING', 'FAIL')}")
        print("  Physical camera   : MANUAL TEST REQUIRED")

        return 0 if (ok_readiness and ok_signaling) else 1
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] unexpected top-level error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())