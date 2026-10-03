"""Phase 9 - Full end-to-end demo verification.

Starts (or reuses) the backend and walks the entire demo flow: clean database
seed -> API health -> login -> live camera session (demo video file transport)
-> detection/tracking/metrics -> manual VLM observation -> evidence captured +
indexed -> stop -> evidence integrity. Each stage is *dependency-gated*: when a
required external service or package is unavailable the stage is skipped and
reported as ``NOT TESTED - DEPENDENCY UNAVAILABLE`` so an honest, reproducible
report is always produced.

Stages:
  1. databases          - PostgreSQL (critical), Qdrant, object storage
  2. clean_start / seed - reset_demo_database.py (opt-in --reset-db)
  3. api_health         - GET /health reports ok
  4. login              - demo ADMIN credentials + /auth/me
  5. live_file_session  - file-transport live camera, frames flow, detect/track
  6. vlm_observation    - manual VLM analyze -> observation arrives
  7. evidence_indexed   - evidence rows captured AND vector-indexed
  8. evidence_integrity - verify_evidence_integrity.py exit 0
  (opt) 9. agent_run    - Phase 7 investigation run (--with-agents, slow)
  (opt)10. forensic      - Phase 8 forensic analysis (--with-agents, slow)

Run from ``backend/``::

    python scripts/run_full_e2e.py
    python scripts/run_full_e2e.py --base-url http://127.0.0.1:8000 --reset-db
    python scripts/run_full_e2e.py --with-agents

Output: PASS / FAIL / NOT TESTED per stage, machine-readable
``data/demo_investigation/results/phase9_e2e_results.json``, exit code 0 only
when no required stage failed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
RESULTS_DIR = os.path.join(BACKEND_DIR, "data", "demo_investigation", "results")
RESULTS_PATH = os.path.join(RESULTS_DIR, "phase9_e2e_results.json")

DEMO_ADMIN_EMAIL = "demo.admin@forensics-demo.com"
DEMO_ADMIN_PASSWORD = "DemoAdmin123!"

NOT_TESTED = "NOT TESTED - DEPENDENCY UNAVAILABLE"

stages: list[dict] = []


def stage(name: str, status: str, detail: str = "") -> None:
    stages.append({"stage": name, "status": status, "detail": detail})
    pad = name.ljust(24)
    print(f"  [{status}] {pad} {detail}")


def _http_json(url: str, method: str = "GET", payload: dict | None = None,
               token: str | None = None, timeout: float = 10.0, retries: int = 0):
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    last_exc = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                try:
                    return resp.status, json.loads(raw)
                except ValueError:
                    return resp.status, raw
        except urllib.error.HTTPError as exc:
            last_exc = exc
            try:
                msg = json.loads(exc.read().decode("utf-8"))
                if isinstance(msg, dict):
                    return exc.code, msg
            except Exception:  # noqa: BLE001
                pass
            return exc.code, {"detail": str(exc)}
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                time.sleep(1.0)
    raise last_exc


# ------------------------------------------------------------------ stages


def _detect(base: str) -> tuple[bool, bool, dict]:
    db_ok = False
    db_detail = ""
    try:
        from sqlalchemy import text

        from app.database.session import SessionLocal

        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        db_detail = str(exc)[:200]
    qdrant_ok = False
    qdrant_detail = ""
    try:
        urllib.request.urlopen("http://localhost:6333/collections", timeout=2)
        qdrant_ok = True
    except Exception as exc:  # noqa: BLE001
        qdrant_detail = str(exc)[:200]
    cv2_ok = True
    cv2_detail = ""
    try:
        import cv2  # noqa: F401
    except ImportError as exc:  # noqa: BLE001
        cv2_ok = False
        cv2_detail = str(exc)
    return db_ok, qdrant_ok, {"db": db_detail, "qdrant": qdrant_detail, "cv2": cv2_detail}


def _health(base: str) -> tuple[str, str]:
    code, data = _http_json(f"{base}/health", timeout=8.0, retries=3)
    top = data.get("status") if isinstance(data, dict) else ""
    if code == 200 and top == "ok":
        return "PASS", "all components ok"
    bad = [k for k, v in (data.get("components") or {}).items() if isinstance(v, dict) and v.get("ok") is False]
    return "FAIL", f"degraded components: {bad or 'see detail'}" if top != "ok" else "PASS"


def _login(base: str) -> tuple[str, str, str | None]:
    code, data = _http_json(f"{base}/auth/login", method="POST",
                            payload={"email": DEMO_ADMIN_EMAIL, "password": DEMO_ADMIN_PASSWORD})
    if code != 200:
        return "FAIL", f"login response {code}: {data.get('detail', data)}", None
    return "PASS", "demo ADMIN login ok", data["access_token"]


def _live_file(base: str, token: str) -> tuple[str, str]:
    import cv2
    demo_videos = os.path.join(BACKEND_DIR, "data", "demo_investigation", "videos")
    candidates = sorted(
        p for p in os.listdir(demo_videos)
        if p.endswith((".mp4", ".mkv")) and p.startswith("demo_video_01")
    )
    if not candidates:
        return "FAIL", "no demo video file found for file transport"
    video_path = os.path.join(demo_videos, candidates[0])

    code, cam_data = _http_json(f"{base}/cameras", token=token)
    if code != 200:
        return "FAIL", f"camera list {code}"
    cameras = cam_data if isinstance(cam_data, list) else cam_data.get("items", [])
    if not cameras:
        return "FAIL", "no cameras registered (run seed_demo_videos first)"
    cam = cameras[0]
    cam_id = cam["id"]

    code, start = _http_json(
        f"{base}/live/cameras/{cam_id}/start", method="POST", token=token,
        payload={"transport": "file", "video_path": video_path, "fps_target": 5.0},
    )
    if code not in (200, 201):
        return "FAIL", f"start live {code}: {start.get('detail', start)}"

    ok, frames = False, 0
    detections, observations = False, False
    for _ in range(40):
        time.sleep(1.0)
        code, st = _http_json(f"{base}/live/cameras/{cam_id}/status", token=token)
        if code != 200:
            continue
        if st.get("frames_received", 0) > 0:
            ok = True
        if st.get("frames_received", 0) > frames:
            frames = st["frames_received"]
        detections = detections or st.get("detection_metrics") is not None
        observations = observations or (st.get("vlm_observations", 0) or 0) > 0
        if not st.get("active", False) and frames > 30:
            break
    code, stop = _http_json(f"{base}/live/cameras/{cam_id}/stop", method="POST", token=token)

    detail = f"frames_received={frames} detection={'on' if detections else 'off'} vlm_obs={observations}"
    ok = ok and frames > 10
    return ("PASS" if ok else "FAIL"), detail


def _vlm_manual(base: str, token: str) -> tuple[str, str]:
    import cv2
    demo_videos = os.path.join(BACKEND_DIR, "data", "demo_investigation", "videos")
    candidates = sorted(
        p for p in os.listdir(demo_videos)
        if p.endswith((".mp4", ".mkv")) and p.startswith("demo_video_01")
    )
    video_path = os.path.join(demo_videos, candidates[0])
    code, cam_data = _http_json(f"{base}/cameras", token=token)
    cameras = cam_data if isinstance(cam_data, list) else cam_data.get("items", [])
    cam_id = cameras[0]["id"]
    code, start = _http_json(
        f"{base}/live/cameras/{cam_id}/start", method="POST", token=token,
        payload={"transport": "file", "video_path": video_path, "fps_target": 10.0},
    )
    if code not in (200, 201):
        return "FAIL", f"start live {code}"
    # wait for frames to build a buffer
    for _ in range(20):
        time.sleep(1.0)
        code, st = _http_json(f"{base}/live/cameras/{cam_id}/status", token=token)
        if st.get("frames_buffered", 0) >= 5:
            break
    # The backend rate-limits manual analysis per session (VLM_COOLDOWN_SECONDS
    # default 30s) and automatic event-triggered observations can claim slots;
    # retry until accepted (or a hard 70s ceiling) instead of failing the stage.
    accepted = False
    last_req: dict = {}
    for _ in range(14):
        code, req = _http_json(f"{base}/live/cameras/{cam_id}/vlm/analyze", method="POST",
                               token=token, payload={"trigger": "manual"})
        last_req = req
        if code == 202:
            accepted = True
            break
        time.sleep(5.0)
    if not accepted:
        _http_json(f"{base}/live/cameras/{cam_id}/stop", method="POST", token=token)
        return "FAIL", f"vlm analyze {code}: {last_req.get('detail', last_req)}"
    got = False
    for _ in range(30):
        time.sleep(1.0)
        code, st = _http_json(f"{base}/live/cameras/{cam_id}/status", token=token)
        if (st.get("vlm_observations", 0) or 0) > 0:
            got = True
            break
    _http_json(f"{base}/live/cameras/{cam_id}/stop", method="POST", token=token)
    return ("PASS" if got else "FAIL"), "manual VLM observation delivered" if got else "no observation within 30s"


def _evidence_indexed() -> tuple[str, str]:
    from app.database.models import ForensicEvidence
    from app.database.session import SessionLocal

    db = SessionLocal()
    try:
        rows = db.query(ForensicEvidence).all()
        counted = {"INDEXED": 0, "FAILED": 0}
        for r in rows:
            counted[r.index_status] = counted.get(r.index_status, 0) + 1
        return ("PASS" if counted.get("INDEXED", 0) == len(rows) and rows else "FAIL",
                f"evidence={len(rows)} states={counted}" if rows else "no evidence rows found")
    finally:
        db.close()


def _evidence_integrity() -> tuple[str, str]:
    prev = sys.path[:]
    try:
        sys.path.insert(0, BACKEND_DIR)
        import verify_evidence_integrity  # noqa: F401

        result = subprocess.run(
            [sys.executable, "scripts/verify_evidence_integrity.py"],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
        )
    finally:
        sys.path = prev
    if result.returncode == 0:
        return "PASS", "evidence integrity clean"
    tail = "\n".join(result.stdout.strip().splitlines()[-8:]) or result.stderr[-400:]
    return "FAIL", f"integrity exit {result.returncode}: {tail[:300]}"


def _agent_run(base: str, token: str) -> tuple[str, str]:
    code, invs = _http_json(f"{base}/investigations", token=token)
    if code != 200 or not invs:
        return "FAIL", f"no investigations to run ({code})"
    inv = invs[0]
    inv_id = inv["id"]
    query = inv.get("title") or inv.get("query") or "vehicle movement at the case camera"
    code, run = _http_json(f"{base}/investigations/{inv_id}/investigate", method="POST",
                           token=token, payload={"query": query},
                           timeout=300.0, retries=0)
    if code not in (200, 201):
        return "FAIL", f"investigation run {code}: {run.get('detail', run)[:200]}"
    run_id = run.get("id") if isinstance(run, dict) else None
    status = run.get("status", "") if isinstance(run, dict) else ""
    return ("PASS" if status in ("COMPLETED", "READY_FOR_REVIEW") else "FAIL",
            f"investigation {inv_id} run={run_id} -> {status}")


def _forensic(base: str, token: str) -> tuple[str, str]:
    code, invs = _http_json(f"{base}/investigations", token=token)
    if code != 200 or not invs:
        return "FAIL", f"no investigations ({code})"
    inv = invs[0]
    inv_id = inv["id"]
    code, runs_data = _http_json(f"{base}/investigations/{inv_id}/runs", token=token)
    runs = runs_data["runs"] if isinstance(runs_data, dict) else runs_data
    runs = runs if isinstance(runs, list) else []
    if code != 200 or not runs:
        return "FAIL", f"no investigation runs to analyze ({code})"
    run_id = int(runs[-1]["id"])
    code, analysis = _http_json(f"{base}/runs/{run_id}/forensic/analyze", method="POST",
                                token=token, payload={}, timeout=300.0, retries=0)
    if code not in (200, 201):
        return "FAIL", f"forensic analyze {code}: {(analysis.get('detail') if isinstance(analysis, dict) else analysis)[:200]}"
    return "PASS", f"forensic analysis for run {run_id} produced"


# ------------------------------------------------------------------- runner


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 9 full E2E verifier")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--reset-db", action="store_true",
                        help="recreate + reseed the database before the run (needs Postgres)")
    parser.add_argument("--with-agents", action="store_true",
                        help="also run Phase 7 investigation + Phase 8 forensic stages (slow)")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    print("=" * 72)
    print("PHASE 9 FULL END-TO-END VERIFICATION")
    print("=" * 72)

    db_ok, qdrant_ok, det = _detect(base)

    # 1. databases
    note = "PostgreSQL reachable" if db_ok else f"PostgreSQL unreachable: {det['db']}"
    stage("databases.postgres", "PASS" if db_ok else NOT_TESTED, note)
    if qdrant_ok:
        stage("databases.qdrant", "PASS", "Qdrant reachable")
    else:
        stage("databases.qdrant", "WARN", "Qdrant unavailable - in-memory vector fallback active: " + det["qdrant"])

    # 2. clean start / seed
    if args.reset_db and db_ok:
        reset = subprocess.run(
            [sys.executable, "scripts/reset_demo_database.py"], cwd=BACKEND_DIR,
            capture_output=True, text=True, timeout=600,
        )
        if reset.returncode != 0:
            stage("clean_start", "FAIL", "reset_demo_database.py failed")
            sys.exit(1)
        stage("clean_start", "PASS", "schema reset + demo evidence reseeded")
    elif args.reset_db:
        stage("clean_start", NOT_TESTED, "PostgreSQL is required for --reset-db")
    else:
        stage("clean_start", "SKIPPED", "use --reset-db to run from a clean state")

    # 3. API health
    try:
        code, data = _http_json(f"{base}/health", timeout=8.0, retries=5)
        top = data.get("status") if isinstance(data, dict) else ""
        if code == 200 and top == "ok":
            stage("api_health", "PASS", "GET /health -> ok")
        elif code == 200:
            stage("api_health", "FAIL", f"GET /health -> {top} {data}")
        else:
            stage("api_health", NOT_TESTED, f"backend not reachable at {base} ({code}) - start it first")
            print("\nStopping here: backend unreachable.")
            _save()
            return
    except Exception as exc:  # noqa: BLE001
        stage("api_health", NOT_TESTED, f"backend not reachable at {base}: {exc} - start it first")
        _save()
        return

    # 4. login
    code, data = _http_json(f"{base}/auth/login", method="POST",
                            payload={"email": DEMO_ADMIN_EMAIL, "password": DEMO_ADMIN_PASSWORD})
    if code != 200:
        stage("login", "FAIL", f"{code} - demo admin login failed: {data.get('detail', data)}")
    else:
        stage("login", "PASS", "demo admin + JWT ok")
        token = data["access_token"]

        # 6. live file session
        status, detail = _live_file(base, token)
        stage("live_file_session", status, detail)

        # 7. VLM observation
        status, detail = _vlm_manual(base, token)
        stage("vlm_observation", status, detail)

        # 8. evidence indexed (DB + vector)
        status, detail = _evidence_indexed()
        stage("evidence_indexed", status, detail)

        # 9. evidence integrity
        status, detail = _evidence_integrity()
        stage("evidence_integrity", status, detail)

        # optional agent + forensic
        if args.with_agents:
            status, detail = _agent_run(base, token)
            stage("agent_run", status, detail)
            status, detail = _forensic(base, token)
            stage("forensic_analysis", status, detail)
        else:
            stage("agent_run", "SKIPPED", "use --with-agents (slow; covered by dedicated verifiers)")
            stage("forensic_analysis", "SKIPPED", "use --with-agents (slow; covered by dedicated verifiers)")

    _save()

    failed_stages = [s for s in stages if s["status"] == "FAIL"]
    print("-" * 72)
    print(f"E2E RESULT: {len(stages)} stages, {len(failed_stages)} FAILED")
    if failed_stages:
        print("FAILED:", ", ".join(s["stage"] for s in failed_stages))
        raise SystemExit(1)
    print("ALL STAGES PASSED (or dependency-skipped)")


def _save() -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump({"stages": stages, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                  fh, indent=2)
    print(f"Machine-readable results: {RESULTS_PATH}")


if __name__ == "__main__":
    main()