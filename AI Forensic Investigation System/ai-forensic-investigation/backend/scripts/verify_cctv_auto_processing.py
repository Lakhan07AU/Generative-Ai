"""CCTV auto-processing supervisor self-test (runs against a live backend).

Four sections:

    1. READINESS - /health and login against the backend.
    2. SUPERVISOR ENGINE - the supervisor reconcile loop is exercised in-process
       and deterministically: a temporary ``auto_process`` camera (RFC 5737
       doc-range RTSP URL) is started through ``AutoProcessSupervisor.poll()``
       with a stub source, its health row converges to ONLINE, a second poll is
       idempotent, and clearing the flag tears the supervised session down.
       The camera + any session rows are removed afterward. Requires NO camera.
    3. LIVE SESSION - optional: when ``--stream-url`` is supplied a manual
       ``POST /live/cameras/<id>/start`` with ``transport=rtsp`` must return a
       LIVE session and then a clean stop. NOT TESTED when no URL is given.
    4. HARDWARE - a physical camera + ``LIVE_AUTO_PROCESS_ENABLED`` deployment
       banner, reported honestly (never fabricated).

Exit code 0 = READINESS + SUPERVISOR ENGINE pass (sections 3/4 are optional).

Usage:
    python scripts/verify_cctv_auto_processing.py [--base-url http://127.0.0.1:8000]
                                                  [--email ...] [--password ...]
                                                  [--stream-url rtsp://...]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL_DEFAULT = "http://127.0.0.1:8000"
DEMO_EMAIL = "demo.investigation@forensics-demo.com"
DEMO_PASSWORD = "demo-investigation-2026"
DOC_URL = "rtsp://203.0.113.77:554/stream"  # RFC 5737 - never a real host


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


def record(ok: bool, name: str, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return bool(ok)


def verify_readiness(base: str, email: str, password: str) -> tuple[bool, Optional[str]]:
    ok = True
    token: Optional[str] = None
    try:
        health = http_json(f"{base}/health")
        ok &= record(health.get("status") in (None, "ok", "OK"), "/health responds",
                     f"status={health.get('status', 'n/a')}")
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "/health responds", f"{exc}")
    try:
        login = http_json(f"{base}/auth/login", "POST", {"email": email, "password": password})
        token = login.get("access_token") or login.get("token")
        ok &= record(bool(token), "login obtains JWT", f"user={email}")
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "login obtains JWT", f"{exc}")
    return ok, token


class _StubSource:
    """Deterministic source: reports healthy, feeds no frames, records start/stop."""

    def __init__(self, runtime, camera):
        self.runtime = runtime
        self.camera = camera
        self.on_finished = None
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def health(self):
        return {
            "source": "rtsp",
            "alive": True,
            "running": True,
            "opened": True,
            "error": None,
            "restarts": 0,
            "last_frame_at": time.time(),
        }


def verify_supervisor_engine() -> bool:
    """Drive AutoProcessSupervisor.poll() in-process against the live DB."""
    ok = True
    from app.database.session import SessionLocal
    from app.database.models import Camera, CameraSession
    from app.live.auto_process import AutoProcessSupervisor
    from app.live.manager import manager

    db = SessionLocal()
    cam = Camera(camera_name="__verify_auto_process__", auto_process=True, rtsp_url=DOC_URL)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    cam_id = cam.id

    sup = AutoProcessSupervisor(
        manager,
        enabled=True,
        min_restart_interval=0.0,
        run_detection=False,
        source_factory=lambda runtime, camera: _StubSource(runtime, camera),
    )
    try:
        summary = sup.poll()
        runtime = manager.get(cam_id)
        started_ok = summary["started"] == 1 and runtime is not None
        ok &= record(started_ok, "auto-process starts a session",
                     f"summary={summary}" if not started_ok else "transport=rtsp")

        db.refresh(cam)
        ok &= record(cam.health_status == "ONLINE",
                     "camera health converges ONLINE", f"status={cam.health_status}")
        ok &= record(cam.last_seen_at is not None, "last_seen_at persisted", "")
        ok &= record(cam.reconnect_attempts == 0, "reconnect_attempts persisted", "")

        summary2 = sup.poll()
        ok &= record(summary2["kept"] == 1 and summary2["started"] == 0,
                     "reconcile is idempotent (kept=1, started=0)", f"{summary2}")

        cam.auto_process = False
        db.commit()
        summary3 = sup.poll()
        stopped = summary3["stopped"] == 1 and manager.get(cam_id) is None
        ok &= record(stopped, "clearing auto_process stops the session", f"{summary3}")
    finally:
        sup.stop()
        manager.clear()
        # Clean the camera + any session/health rows created for verification.
        try:
            db.query(CameraSession).filter(CameraSession.camera_id == cam_id).delete()
            db.query(Camera).filter(Camera.id == cam_id).delete()
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        db.close()
    return ok


def verify_live_session(base: str, token: str, stream_url: str) -> bool:
    """POST /start transport=rtsp against the live API (needs a real stream)."""
    ok = True
    camera_id = None
    try:
        body = http_json(f"{base}/cameras", "POST",
                         {"camera_name": "__verify_rtsp_live__", "camera_type": "CCTV",
                          "rtsp_url": stream_url, "auto_process": False},
                         token=token)
        camera_id = body.get("id")
        if body.get("detail") or camera_id is None:
            ok &= record(False, "create verification camera", f"{body.get('detail') or 'no id'}")
            return False
        ok &= record(True, "create verification camera", f"id={camera_id}")
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "create verification camera", f"{exc}")
        return False

    try:
        start = http_json(f"{base}/live/cameras/{camera_id}/start", "POST",
                          {"transport": "rtsp", "stream_url": stream_url}, token=token)
        ok &= record(start.get("status") == "LIVE", "RTSP session starts LIVE",
                     f"status={start.get('status')}")
    except Exception as exc:  # noqa: BLE001
        ok &= record(False, "RTSP session starts LIVE", f"{exc}")
    finally:
        try:
            http_json(f"{base}/live/cameras/{camera_id}/stop", "POST", {}, token=token)
        except Exception:  # noqa: BLE001
            pass
        # No DELETE /cameras endpoint exists, so clean the row in-process.
        from app.database.session import SessionLocal
        from app.database.models import Camera, CameraSession

        db = SessionLocal()
        try:
            db.query(CameraSession).filter(CameraSession.camera_id == camera_id).delete()
            db.query(Camera).filter(Camera.id == camera_id).delete()
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        finally:
            db.close()
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=BASE_URL_DEFAULT)
    ap.add_argument("--email", default=DEMO_EMAIL)
    ap.add_argument("--password", default=DEMO_PASSWORD)
    ap.add_argument("--stream-url", default=None,
                    help="real RTSP URL to verify a manual rtsp session over the live API")
    ap.add_argument("--timeout", type=float, default=8.0)
    args = ap.parse_args(argv)

    print("== CCTV auto-processing verification ==\n-- readiness --")
    ok_readiness, token = verify_readiness(args.base_url, args.email, args.password)

    print("\n-- supervisor engine (in-process, no camera) --")
    ok_engine = verify_supervisor_engine()

    print("\n-- live session (optional) --")
    live_status = "NOT TESTED"
    if not args.stream_url:
        print(f"  [NOT TESTED] no --stream-url supplied")
    elif not token:
        live_status = "NOT TESTED"
        print(f"  [NOT TESTED] no token from readiness")
    else:
        live_status = "PASS" if verify_live_session(args.base_url, token, args.stream_url) else "FAIL"

    from app.core.config import settings
    print("\n-- deployment banner --")
    banner_parts = [
        f"LIVE_AUTO_PROCESS_ENABLED={settings.LIVE_AUTO_PROCESS_ENABLED}",
        f"LIVE_AUTO_PROCESS_DETECTION={settings.LIVE_AUTO_PROCESS_DETECTION}",
        f"LIVE_AUTO_PROCESS_POLL_SECONDS={settings.LIVE_AUTO_PROCESS_POLL_SECONDS}",
    ]
    if not settings.LIVE_AUTO_PROCESS_ENABLED:
        print(f"  [NOT TESTED] supervisor is disabled by config ({', '.join(banner_parts)}) -")
        print("               enable LIVE_AUTO_PROCESS_ENABLED in the deployment to run on camera hardware")
    else:
        print(f"  [INFO] supervisor enabled ({', '.join(banner_parts)})")

    print("\n  verdicts:")
    print(f"    Backend readiness     : {'PASS' if ok_readiness else 'FAIL'}")
    print(f"    Supervisor engine     : {'PASS' if ok_engine else 'FAIL'}")
    print(f"    Live RTSP session     : {live_status}")

    hard_ok = ok_readiness and ok_engine
    soft_ok = live_status in ("PASS", "NOT TESTED")
    return 0 if (hard_ok and soft_ok) else 1


if __name__ == "__main__":
    sys.exit(main())