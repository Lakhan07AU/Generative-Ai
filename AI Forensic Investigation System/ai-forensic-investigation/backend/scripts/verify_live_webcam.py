"""FULL live pipeline test driven by a REAL laptop webcam device.

Chain under test (no simulation, no demo video, no synthetic frames)::

    laptop webcam -> WebcamCameraSource -> ingest -> sampling -> rolling buffer
      -> YOLO -> tracking -> events -> ForensicEvidence
      -> PostgreSQL + MinIO (sha256) -> Qdrant -> VLM

The script talks to a RUNNING backend over its public API (default
http://127.0.0.1:8000) and starts a real session with ``transport="webcam"``.
It never claims success without a physically opened device: if the backend
cannot open the capture device, the run ends as FAIL with the exact blocker.

Usage:
    python scripts/verify_live_webcam.py --base-url http://127.0.0.1:8000 \
        --device 0 --seconds 45

Exit code 0 = RESULT: PASS, 1 = RESULT: FAIL.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

BASE_URL_DEFAULT = "http://127.0.0.1:8000"
DEMO_EMAIL = "demo.investigation@forensics-demo.com"
DEMO_PASSWORD = "demo-investigation-2026"

CHECKS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return bool(ok)


def http(url: str, method: str = "GET", body=None, token: str | None = None, timeout: float = 30.0):
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
        return json.loads(raw.decode("utf-8", "replace")) if raw else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Full live webcam pipeline verification")
    parser.add_argument("--base-url", default=BASE_URL_DEFAULT)
    parser.add_argument("--email", default=DEMO_EMAIL)
    parser.add_argument("--password", default=DEMO_PASSWORD)
    parser.add_argument("--device", type=int, default=None, help="OpenCV device index")
    parser.add_argument("--seconds", type=float, default=45.0)
    parser.add_argument("--camera-name", default="Laptop Webcam Verification")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("\nFULL LIVE WEBCAM PIPELINE TEST")
    print("=" * 60)
    print(f"base-url: {base}")

    try:
        login = http(f"{base}/auth/login", "POST",
                     {"email": args.email, "password": args.password})
        token = login.get("access_token")
        record("login", bool(token), args.email)
    except Exception as exc:  # noqa: BLE001
        record("login", False, str(exc))
        print("\nRESULT: FAIL (backend unreachable or auth failed)")
        return 1

    health = http(f"{base}/health")
    record("backend /health", isinstance(health, dict), f"status={health.get('status', 'n/a')}")

    # -- camera -------------------------------------------------------------
    camera_id = None
    try:
        cam = http(f"{base}/cameras", "POST", {
            "camera_name": args.camera_name,
            "location": "verification-host",
            "camera_type": "OTHER",
        }, token=token)
        camera_id = cam.get("id")
        record("camera created", bool(camera_id), f"camera_id={camera_id}")
    except Exception as exc:  # noqa: BLE001
        record("camera created", False, str(exc))

    if camera_id is None:
        print("\nRESULT: FAIL (no camera to attach the webcam to)")
        return 1

    # -- real device start --------------------------------------------------
    body = {"transport": "webcam", "fps_target": 10}
    if args.device is not None:
        body["device_index"] = args.device
    started = False
    try:
        resp = http(f"{base}/live/cameras/{camera_id}/start", "POST", body, token=token)
        started = True
        record("webcam transport accepted", True,
               f"session_id={resp.get('id')} transport={resp.get('transport')}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        record("webcam transport accepted", False, f"HTTP {exc.code}: {detail}")
    except Exception as exc:  # noqa: BLE001
        record("webcam transport accepted", False, str(exc))

    if not started:
        print("\n  BLOCKER: the backend could not open a real capture device.")
        print("  A laptop webcam is NOT reachable from a Linux container")
        print("  (Docker Desktop does not pass /dev/video* through).")
        print("  Run the backend natively on the Windows host, or attach the")
        print("  device with --device <index> after probing on the host:")
        print("      python scripts/verify_webcam.py --probe")
        print("\nRESULT: FAIL")
        return 1

    print(f"\n  capturing for {args.seconds:.0f}s (place objects in view: "
          f"person, chair, laptop, bottle, phone where detectable)\n")

    # -- live observation ---------------------------------------------------
    deadline = time.time() + args.seconds
    last: dict = {}
    while time.time() < deadline:
        time.sleep(2.0)
        try:
            last = http(f"{base}/live/cameras/{camera_id}/status", token=token)
        except Exception:  # noqa: BLE001
            continue
        print(f"  t+{args.seconds - (deadline - time.time()):5.1f}s  "
              f"frames={last.get('frames_received')} "
              f"sampled={last.get('frames_sampled')} "
              f"det={last.get('detection_recent_count')} "
              f"tracks={last.get('active_tracks')} "
              f"events={last.get('total_events')} "
              f"evidence={last.get('evidence_captured')}")

    src_health = last.get("source_health") or {}
    record("camera source alive", bool(src_health.get("alive")),
           f"opened={src_health.get('opened')} frames_read={src_health.get('frames_read')} "
           f"dropped={src_health.get('dropped_frames')} restarts={src_health.get('restarts')} "
           f"error={src_health.get('error')}")
    record("frames received", (last.get("frames_received") or 0) > 0,
           f"frames_received={last.get('frames_received')}")
    record("frames sampled into buffer", (last.get("frames_sampled") or 0) > 0,
           f"frames_sampled={last.get('frames_sampled')}")
    record("YOLO detection enabled", bool(last.get("detection_enabled")),
           f"metrics={last.get('detection_metrics')} err={last.get('detection_error')}")
    record("tracking enabled", bool(last.get("tracking_enabled")),
           f"active_tracks={last.get('active_tracks')}")
    record("events recorded", (last.get("total_events") or 0) > 0,
           f"events={last.get('total_events')}")
    record("evidence captured", (last.get("evidence_captured") or 0) > 0,
           f"captured={last.get('evidence_captured')} failed={last.get('evidence_failed')} "
           f"err={last.get('evidence_last_error')}")
    record("evidence indexed (Qdrant)", (last.get("evidence_indexed") or 0) > 0,
           f"indexed={last.get('evidence_indexed')}")
    vlm_status = "NOT TESTED"
    if last.get("vlm_observations"):
        vlm_status = "PASS"
    record("VLM observations", bool(last.get("vlm_observations")),
           f"observations={last.get('vlm_observations')} enabled={last.get('vlm_enabled')} "
           f"err={last.get('vlm_last_error')} -> {vlm_status}")

    # -- stop ---------------------------------------------------------------
    try:
        http(f"{base}/live/cameras/{camera_id}/stop", "POST", {}, token=token)
        record("session stopped", True, f"camera_id={camera_id}")
    except Exception as exc:  # noqa: BLE001
        record("session stopped", False, str(exc))

    # -- evidence records ---------------------------------------------------
    try:
        rows = http(f"{base}/evidence/live?camera_id={camera_id}", token=token)
        rows = rows if isinstance(rows, list) else (rows or {}).get("items", [])
        record("evidence rows in PostgreSQL", len(rows) > 0, f"rows={len(rows)}")
        if rows:
            row = rows[0]
            fields = ("camera_id", "session_id", "frame_sequence", "frame_timestamp",
                      "event_id", "track_id", "sha256", "storage_path")
            present = {f: bool((row.get(f) not in (None, ""))) for f in fields}
            record("evidence provenance fields populated", all(present.values()),
                   ",".join(f for f, ok in present.items() if not ok) or "all present")
    except Exception as exc:  # noqa: BLE001
        record("evidence rows in PostgreSQL", False, str(exc))

    # -- summary ------------------------------------------------------------
    failed = [n for n, ok, _ in CHECKS if not ok]
    print("\n" + "=" * 60)
    if failed:
        print(f"RESULT: FAIL ({len(failed)}/{len(CHECKS)} checks failed: {', '.join(failed)})")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
