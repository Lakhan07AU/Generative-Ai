"""QR camera pairing self-test (runs against a live backend, no device needed).

Walks the full pairing lifecycle over real HTTP/WebSocket:

    1. READINESS - /health, login, camera list.
    2. QR PAIRING - creates a MOBILE camera, POSTs /live/cameras/<id>/pair,
       fetches the QR PNG (checks the PNG magic), and verifies the pairing URL
       targets the QR mobile page with camera_id + pair.
    3. PAIRING SIGNALING - connects to the real signaling WebSocket, sends
       {"type":"auth","pair":...}, expects auth_ok, closes with bye/bye_ack,
       then confirms the code is single-use (replay -> error + close).

Prints the section matrix and verdicts:

    Backend readiness   : PASS / FAIL
    QR pairing          : PASS / FAIL
    Pairing signaling   : PASS / FAIL

Exit code 0 = all sections PASS; 1 otherwise.

Usage:
    python scripts/verify_qr_pairing.py [--base-url http://127.0.0.1:8000]
                                        [--email ...] [--password ...]
                                        [--cleanup]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import urllib.error
import urllib.request

BASE_URL_DEFAULT = "http://127.0.0.1:8000"
DEMO_EMAIL = "demo.investigation@forensics-demo.com"
DEMO_PASSWORD = "demo-investigation-2026"

STATUSES: dict[str, str] = {}


def http_json(url: str, method: str = "GET", body=None, token: str | None = None, timeout: float = 15.0):
    req = urllib.request.Request(
        url,
        data=(json.dumps(body).encode() if body is not None else None),
        method=method,
    )
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8", "replace"))


def record(ok: bool, name: str, detail: str = "", section: str = "MISC") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return bool(ok)


def set_section(section: str, ok: bool) -> None:
    prev = STATUSES.get(section, "PASS")
    if prev == "FAIL":
        return
    STATUSES[section] = "PASS" if ok else "FAIL"


# ------------------------------------------------------------------ READINESS


def verify_readiness(base: str, email: str, password: str) -> tuple[bool, str | None]:
    sec = "READINESS"
    ok = True
    token: str | None = None

    try:
        health = http_json(f"{base}/health")
        ok &= record(health.get("status") in (None, "ok", "OK"), "/health responds",
                     f"status={health.get('status', 'n/a')}", sec)
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "/health responds", f"{exc}", sec)

    try:
        login = http_json(f"{base}/auth/login", "POST", {"email": email, "password": password})
        token = login.get("access_token") or login.get("token")
        ok &= record(bool(token), "login obtains JWT", f"user={email}", sec)
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "login obtains JWT", f"{exc}", sec)

    if not token:
        set_section(sec, ok)
        return ok, token

    try:
        cams = http_json(f"{base}/cameras", token=token)
        ok &= record(isinstance(cams, list), "camera list reachable",
                     f"{len(cams)} cameras", sec)
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "camera list reachable", f"{exc}", sec)

    set_section(sec, ok)
    return ok, token


# --------------------------------------------------------------- QR PAIRING


def verify_qr_pairing(base: str, token: str) -> tuple[bool, dict | None]:
    """Create a MOBILE camera, create a pairing, fetch the QR PNG, validate."""
    sec = "QR PAIRING"
    ok = True
    cam: dict | None = None
    pairing: dict | None = None
    created_cam_id: int | None = None

    suffix = random.randint(10_000, 99_999)
    try:
        cam = http_json(f"{base}/cameras", "POST",
                        {"camera_name": f"QR-VERIFY-{suffix}", "location": "self-test",
                         "camera_type": "MOBILE"}, token=token)
        created_cam_id = cam.get("id")
        ok &= record(created_cam_id is not None, "creates a MOBILE test camera",
                     f"id={created_cam_id}", sec)
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "creates a MOBILE test camera", f"{exc}", sec)

    if created_cam_id is None:
        set_section(sec, ok)
        return ok, {"camera_id": None, "pairing_id": None}

    try:
        pairing = http_json(f"{base}/live/cameras/{created_cam_id}/pair", "POST", token=token)
        pid = (pairing or {}).get("pairing_id")
        ok &= record(bool(pid) and len(str(pid)) >= 32, "POST /pair returns a token",
                     f"pairing_id={pid}", sec)
        url = (pairing or {}).get("url", "")
        ok &= record("/live/mobile" in url and "camera_id=" in url and "pair=" in url,
                     "pairing URL targets the QR mobile page",
                     url, sec)
        ok &= record((pairing or {}).get("camera_id") == created_cam_id,
                     "pairing is bound to the camera", sec)
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "POST /pair returns a token", f"{exc}", sec)

    if (pairing or {}).get("pairing_id"):
        try:
            req = urllib.request.Request(
                f"{base}/live/cameras/{created_cam_id}/pair/qr.png"
                f"?pairing_id={pairing['pairing_id']}",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
            magic = raw[:8] == b"\x89PNG\r\n\x1a\n"
            ok &= record(magic and ctype == "image/png", "QR endpoint returns a PNG",
                         f"{len(raw)} bytes, content-type={ctype}", sec)
        except urllib.error.HTTPError as exc:
            ok &= record(False, "QR endpoint returns a PNG", f"HTTP {exc.code}", sec)
        except Exception as exc:  # noqa: BLE001
            ok &= record(False, "QR endpoint returns a PNG", f"{exc}", sec)

    set_section(sec, ok)
    return (ok, {"camera_id": created_cam_id, "pairing_id": (pairing or {}).get("pairing_id")})


# ----------------------------------------------------- PAIRING SIGNALING


def _decode_httperror_bytes(exc: urllib.error.HTTPError) -> str:
    try:
        return json.loads(exc.read().decode("utf-8", "replace")).get("detail", str(exc))
    except Exception:  # noqa: BLE001
        return str(exc)


async def _pair_signaling_flow(base: str, camera_id: int, pairing_id: str) -> dict:
    """Use the pairing code over the real signaling socket; expect auth_ok then replay-reject."""
    import websockets

    ws_url = base.replace("http", "ws", 1) + f"/live/cameras/{camera_id}/ws/signaling"
    out = {"auth_ok": False, "bye_ack": False, "replay_rejected": False, "detail": ""}

    try:
        async with websockets.connect(ws_url, open_timeout=15.0) as ws:
            await ws.send(json.dumps({"type": "auth", "pair": pairing_id}))
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
            out["auth_ok"] = msg.get("type") == "auth_ok" and msg.get("camera_id") == camera_id
            if not out["auth_ok"]:
                out["detail"] = f"first auth gave {msg.get('type')}: {msg.get('detail')}"
                return out
            await ws.send(json.dumps({"type": "bye"}))
            bye = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
            out["bye_ack"] = bye.get("type") == "bye_ack"
    except Exception as exc:  # noqa: BLE001
        out["detail"] = f"first connection: {type(exc).__name__}: {exc}"
        return out

    # Replay must be rejected: the code was consumed.
    try:
        async with websockets.connect(ws_url, open_timeout=15.0) as ws:
            await ws.send(json.dumps({"type": "auth", "pair": pairing_id}))
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
            out["replay_rejected"] = msg.get("type") == "error"
            if not out["replay_rejected"]:
                out["detail"] = f"replay gave {msg.get('type')}: {msg.get('detail')}"
    except websockets.exceptions.ConnectionClosedOK:
        out["replay_rejected"] = True
    except Exception as exc:  # noqa: BLE001
        out["detail"] = f"replay: {type(exc).__name__}: {exc}"

    return out


def verify_pair_signaling(base: str, token: str, ids: dict) -> bool:
    sec = "PAIRING SIGNALING"
    ok = True

    if not ids or not ids.get("pairing_id"):
        ok &= record(False, "pairing signaling exercised",
                     "no pairing to use (QR PAIRING section failed)", sec)
        set_section(sec, ok)
        return ok

    try:
        import websockets  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "websockets available in test env", f"{exc}", sec)
        set_section(sec, ok)
        return ok

    camera_id = int(ids["camera_id"])
    pairing_id = str(ids["pairing_id"])
    loop = asyncio.new_event_loop()
    try:
        resp = loop.run_until_complete(_pair_signaling_flow(base, camera_id, pairing_id))
    finally:
        loop.close()

    ok &= record(resp["auth_ok"], "signaling accepts the pairing code (auth_ok)", resp["detail"], sec)
    ok &= record(resp["bye_ack"], "clean bye/bye_ack", "", sec)
    ok &= record(resp["replay_rejected"], "code is single-use (replay rejected)", "", sec)

    set_section(sec, ok)
    return ok


# ------------------------------------------------------------------- CLEANUP


def cleanup(base: str, token: str, ids: dict) -> None:
    """Best-effort cleanup of the test camera via the API (no DELETE exists, so
    it is only removed when run from the backend directory with DB access)."""
    if not ids or not ids.get("camera_id"):
        return
    try:
        from app.core.config import settings
        from app.database.session import SessionLocal
        from app.database.models import Camera, CameraPairing, CameraSession
    except Exception:  # noqa: BLE001
        return

    cam_id = int(ids["camera_id"])
    try:
        db = SessionLocal()
        try:
            db.query(CameraPairing).filter(CameraPairing.camera_id == cam_id).delete()
            db.query(CameraSession).filter(CameraSession.camera_id == cam_id).delete()
            db.query(Camera).filter(Camera.id == cam_id).delete()
            db.commit()
            print(f"  [INFO] cleaned up test camera #{cam_id}")
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        print(f"  [INFO] cleanup skipped ({exc})")


# ------------------------------------------------------------------- MAIN


def main() -> int:
    parser = argparse.ArgumentParser(description="QR camera pairing self-test")
    parser.add_argument("--base-url", default=BASE_URL_DEFAULT)
    parser.add_argument("--email", default=DEMO_EMAIL)
    parser.add_argument("--password", default=DEMO_PASSWORD)
    parser.add_argument("--cleanup", action="store_true", help="delete the test camera/rows after")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print(f"base-url: {base}")

    try:
        ok_readiness, token = verify_readiness(base, args.email, args.password)
        if not token:
            print("\nverdicts:")
            print(f"  Backend readiness : {STATUSES.get('READINESS', 'FAIL')}")
            print(f"  QR pairing        : NOT TESTED (no token)")
            print(f"  Pairing signaling : NOT TESTED (no token)")
            return 1

        ids = None
        ok_qr, ids = verify_qr_pairing(base, token)
        ok_sig = verify_pair_signaling(base, token, ids)

        if args.cleanup:
            cleanup(base, token, ids)

        print("\nsection matrix:")
        for sec in ("READINESS", "QR PAIRING", "PAIRING SIGNALING"):
            print(f"  {STATUSES.get(sec, 'FAIL'):>16}  {sec}")

        print("\nverdicts:")
        print(f"  Backend readiness : {STATUSES.get('READINESS', 'FAIL')}")
        print(f"  QR pairing        : {STATUSES.get('QR PAIRING', 'FAIL')}")
        print(f"  Pairing signaling : {STATUSES.get('PAIRING SIGNALING', 'FAIL')}")

        return 0 if (ok_readiness and ok_qr and ok_sig) else 1
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] unexpected top-level error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())