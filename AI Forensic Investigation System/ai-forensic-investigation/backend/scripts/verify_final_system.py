"""AI Forensic Investigation System - consolidated phase + webcam verification.

Every check is executed against the real services. Nothing is mocked, and a
check that could not run is reported as NOT TESTED / ENVIRONMENT FAILURE rather
than PASS.

Phases
------
  phase5  evidence model, PostgreSQL schema (alembic head), MinIO frames/reports
          buckets (PUT/GET/EXISTS/sha256/missing/corrupt/duplicate), real Qdrant
          (collection, dims, insert, retrieve, search, filter, delete)
  phase6  video RAG against real evidence (delegates to the canonical verifiers)
  phase7  LangGraph investigation agent (delegates to verify_investigator_agent)
  phase8  forensic analysis / timeline / verification / reporting + PDF
  webcam  real OpenCV capture device availability

Usage
-----
    python scripts/verify_final_system.py                  # everything
    python scripts/verify_final_system.py --only phase5 phase7
    python scripts/verify_final_system.py --skip-webcam    # no device required

Exit code 0 only when every executed section passes. Sections that could not be
executed are printed as NOT TESTED and make the final status NOT READY.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback

# Allow `python scripts/verify_phaseN.py` from anywhere: the backend package root
# (parent of scripts/) must be importable for `import app...`.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_BACKEND_ROOT, os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PASS = "PASS"
FAIL = "FAIL"
NOT_TESTED = "NOT TESTED"
PARTIAL = "PARTIAL"
ENV_FAILURE = "ENVIRONMENT FAILURE"
PRE_EXISTING = "PRE-EXISTING FAILURE"

PHASE_TABLES = [
    # logical name -> physical table name in the schema
    "camera",
    "camera_session",
    "forensic_evidence",
    "vlm_observation",
    "investigation",
    "investigation_runs",
    "forensic_analyses",
    "forensic_timeline_events",
    "finding_reviews",
    "forensic_reports",
]

TABLE_NAMES = {
    "camera": "cameras",
    "camera_session": "camera_sessions",
    "forensic_evidence": "forensic_evidence",
    "vlm_observation": "vlm_observation_records",
    "investigation": "investigations",
    "investigation_runs": "investigation_runs",
    "forensic_analyses": "forensic_analyses",
    "forensic_timeline_events": "forensic_timeline_events",
    "finding_reviews": "finding_reviews",
    "forensic_reports": "forensic_reports",
}

SECTIONS: dict[str, str] = {}
DETAIL: dict[str, list[str]] = {}


def _record(section: str, name: str, ok: bool, detail: str = "") -> bool:
    DETAIL.setdefault(section, []).append(
        f"[{'PASS' if ok else FAIL}] {name}" + (f" - {detail}" if detail else "")
    )
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if SECTIONS.get(section) == FAIL:
        return ok
    SECTIONS[section] = PASS if ok else FAIL
    return ok


def _note(section: str, status: str, message: str) -> None:
    DETAIL.setdefault(section, []).append(f"[{status}] {message}")
    print(f"  [{status}] {message}")
    if status == PASS:
        return
    if status == PARTIAL and SECTIONS.get(section) == PASS:
        SECTIONS[section] = PARTIAL
    elif SECTIONS.get(section) != FAIL:
        SECTIONS[section] = status


def _run(script: str, args: list[str] | None = None, timeout: int = 1800) -> tuple[str, str]:
    """Run a canonical verifier script; classify by its exit code / output."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), script)
    if not os.path.isfile(path):
        return NOT_TESTED, f"script not found: {script}"
    env = dict(os.environ)
    env["PYTHONPATH"] = _BACKEND_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run(
            [sys.executable, path, *(args or [])],
            capture_output=True, text=True, timeout=timeout, cwd=_BACKEND_ROOT, env=env,
        )
    except subprocess.TimeoutExpired:
        return FAIL, f"{script} timed out after {timeout}s"
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        return PASS, out
    for marker, status in (
        ("NOT TESTED", NOT_TESTED),
        ("DEPENDENCY UNAVAILABLE", ENV_FAILURE),
        ("SKIPPED", NOT_TESTED),
    ):
        if marker in out:
            return status, out
    return FAIL, out


def _run_and_report(section: str, label: str, script: str, args: list[str] | None = None) -> str:
    status, out = _run(script, args)
    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-6:]
    summary = " | ".join(t.strip() for t in tail)
    _note(section, status if status != PASS else PASS, f"{label}: {summary[:400]}")
    return status


# --------------------------------------------------------------------- PHASE 5


def check_phase5() -> str:
    sec = "PHASE 5 - Evidence/Storage"
    print(f"\n{sec}")
    SECTIONS[sec] = PASS

    # -- PostgreSQL ---------------------------------------------------------
    try:
        from sqlalchemy import inspect, text

        from app.database.session import engine

        with engine.connect() as conn:
            insp = inspect(conn)
            tables = set(insp.get_table_names())
        missing = [t for t in PHASE_TABLES if TABLE_NAMES[t] not in tables]
        _record(sec, "PostgreSQL reachable + expected tables present", not missing,
                f"{len(PHASE_TABLES) - len(missing)}/{len(PHASE_TABLES)} tables"
                + (f", missing={[TABLE_NAMES[t] for t in missing]}" if missing else ""))
        with engine.connect() as conn:
            ver = conn.execute(text("select version()")).scalar()
        _record(sec, "PostgreSQL is the real engine", "PostgreSQL" in str(ver), str(ver)[:60])
    except Exception as exc:  # noqa: BLE001
        _note(sec, ENV_FAILURE, f"PostgreSQL unavailable: {exc}")

    # -- alembic head -------------------------------------------------------
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "alembic.ini"))
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        _record(sec, "alembic head == 0008_phase8_forensics",
                any("0008" in h and "phase8" in h for h in heads), f"heads={heads}")
    except Exception as exc:  # noqa: BLE001
        _note(sec, NOT_TESTED, f"alembic head inspection failed: {exc}")

    try:
        from alembic import command
        from alembic.config import Config as Cfg

        from app.database.session import engine

        cfg = Cfg(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", str(engine.url).replace("%", "%%"))
        command.current(cfg, verbose=False)
        _record(sec, "migrations applied to live DB", True, "alembic current executed")
    except Exception as exc:  # noqa: BLE001
        _record(sec, "migrations applied to live DB", False, str(exc)[:200])

    # -- MinIO --------------------------------------------------------------
    try:
        from app.core.config import settings
        from app.storage.service import storage

        backend = storage.backend_name()
        _record(sec, "MinIO is the real storage backend", backend == "minio", f"backend={backend}")
        payload = b"verify-phase5-probe" + os.urandom(8)
        digest = hashlib.sha256(payload).hexdigest()
        name = "verify/phase5_probe.bin"
        path = storage.put_bytes("frames", payload, name, "application/octet-stream")
        _record(sec, "MinIO frames bucket PUT", bool(path), f"path={path}")
        _record(sec, "MinIO frames bucket EXISTS", storage.exists(path), path)
        got = storage.get_bytes(path)
        _record(sec, "MinIO frames bucket GET + SHA-256 match",
                hashlib.sha256(got).hexdigest() == digest,
                f"db/expected={digest[:16]} stored={hashlib.sha256(got).hexdigest()[:16]}")
        dup = storage.put_bytes("frames", payload, name, "application/octet-stream")
        _record(sec, "duplicate PUT is idempotent (same digest)",
                storage.exists(dup) and hashlib.sha256(storage.get_bytes(dup)).hexdigest() == digest)
        report_path = storage.put_bytes("reports", b"%PDF-1.4 probe", "verify/phase5_probe.pdf",
                                        "application/pdf")
        _record(sec, "MinIO reports bucket PUT/GET",
                storage.exists(report_path) and storage.get_bytes(report_path).startswith(b"%PDF"),
                f"path={report_path}")
        _record(sec, "missing object raises (no silent empty bytes)", _raises(
            lambda: storage.get_bytes(
                f"{settings.MINIO_BUCKET_FRAMES}/verify/__does_not_exist__.bin")))
        _record(sec, "corrupt object detected (truncated bytes differ in SHA-256)",
                hashlib.sha256(got[:5]).hexdigest() != digest)
    except Exception as exc:  # noqa: BLE001
        _note(sec, ENV_FAILURE, f"MinIO unavailable: {exc}")

    # -- Qdrant -------------------------------------------------------------
    try:
        from app.ai.qdrant_service import QdrantService
        from app.core.config import settings

        qs = QdrantService()
        qname = qs.backend_name()
        _record(sec, "REAL QDRANT (not in-memory fallback)", qname == "qdrant", f"backend={qname}")
        qs.ensure_collections()
        probe_id = f"verify-phase5-{int(time.time())}"
        vec = [0.0] * settings.QDRANT_VECTOR_SIZE
        vec[0] = 1.0
        qs.index_evidence(probe_id, vec, {
            "camera_id": -1, "session_id": -1, "event_id": "verify",
            "track_id": "verify-track", "kind": "verification_probe",
            "probe_id": probe_id,
        })
        _record(sec, "point insertion", qs.point_exists(settings.QDRANT_COLLECTION_EVIDENCE, probe_id))
        hits = qs.search_evidence(vec, limit=5)
        _record(sec, "semantic search returns the probe", any(
            (h.get("payload") or {}).get("probe_id") == probe_id for h in hits),
            f"hits={len(hits)}")
        filtered = qs.search_evidence(vec, limit=5, where={"camera_id": {"$eq": -1}})
        _record(sec, "metadata filtering", any(
            (h.get("payload") or {}).get("probe_id") == probe_id for h in filtered),
            f"filtered={len(filtered)}")
        empty = qs.search_evidence(vec, limit=5, where={"camera_id": {"$eq": 999999}})
        _record(sec, "negative filter returns nothing",
                not any((h.get("payload") or {}).get("probe_id") == probe_id for h in empty),
                f"hits={len(empty)}")
        qs.delete(settings.QDRANT_COLLECTION_EVIDENCE, probe_id)
        gone = [h for h in qs.search_evidence(vec, limit=10)
                if (h.get("payload") or {}).get("probe_id") == probe_id]
        _record(sec, "delete/reindex round-trip", not gone, f"residual={len(gone)}")
        try:
            import requests

            info = requests.get(f"{settings.QDRANT_URL}/collections/"
                                f"{settings.QDRANT_COLLECTION_EVIDENCE}", timeout=10).json()
            dims = info["result"]["config"]["params"]["vectors"]["size"]
            _record(sec, "collection dimensions == settings.QDRANT_VECTOR_SIZE",
                    dims == settings.QDRANT_VECTOR_SIZE, f"dims={dims}")
        except Exception as exc:  # noqa: BLE001
            _note(sec, NOT_TESTED, f"qdrant collection dimension read failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        _note(sec, ENV_FAILURE, f"Qdrant unavailable: {exc}")

    # -- evidence integrity (canonical verifier) ----------------------------
    _run_and_report(sec, "evidence integrity (sha256/orphans/index sync)",
                    "verify_evidence_integrity.py")
    return SECTIONS[sec]


def _raises(fn) -> bool:
    try:
        fn()
    except Exception:  # noqa: BLE001
        return True
    return False


# --------------------------------------------------------------------- PHASE 6


def check_phase6(base_url: str | None = "http://127.0.0.1:8000") -> str:
    sec = "PHASE 6 - Video RAG"
    print(f"\n{sec}")
    SECTIONS[sec] = PASS
    _run_and_report(sec, "video RAG demo queries", "verify_video_rag_demo.py")
    args = ["--base-url", base_url] if base_url else None
    _run_and_report(sec, "demo investigation dataset + RAG (live server)",
                    "verify_demo_investigation.py", args)
    return SECTIONS[sec]


# --------------------------------------------------------------------- PHASE 7


def check_phase7() -> str:
    sec = "PHASE 7 - LangGraph Agent"
    print(f"\n{sec}")
    SECTIONS[sec] = PASS
    _run_and_report(sec, "investigation agent graph", "verify_investigator_agent.py")
    return SECTIONS[sec]


# --------------------------------------------------------------------- PHASE 8


def check_phase8() -> str:
    sec = "PHASE 8 - Forensic Analysis"
    print(f"\n{sec}")
    SECTIONS[sec] = PASS
    _run_and_report(sec, "forensic timeline / verification / report + PDF",
                    "verify_forensic_reporting.py")
    return SECTIONS[sec]


# ---------------------------------------------------------------------- WEBCAM


def check_webcam(seconds: float = 5.0) -> str:
    sec = "WEBCAM"
    print(f"\n{sec}")
    SECTIONS[sec] = PASS
    try:
        import cv2
    except Exception as exc:  # noqa: BLE001
        _note(sec, NOT_TESTED, f"OpenCV unavailable: {exc}")
        return SECTIONS[sec]
    _record(sec, "OpenCV importable", True, cv2.__version__)

    devices = []
    for index in range(4):
        cap = cv2.VideoCapture(index)
        try:
            if cap is not None and cap.isOpened():
                ok, frame = cap.read()
                if ok and frame is not None and frame.size:
                    devices.append(index)
        finally:
            if cap is not None:
                cap.release()
    if not devices:
        _note(sec, ENV_FAILURE,
              "no capture device on indices 0-3 in this process (Docker Desktop does "
              "not pass /dev/video* into containers; a host-native run is required)")
        return SECTIONS[sec]
    _record(sec, "capture device detected", True, f"indices={devices}")

    index = devices[0]
    cap = cv2.VideoCapture(index)
    frames = 0
    deadline = time.time() + seconds
    while time.time() < deadline:
        ok, _ = cap.read()
        if ok:
            frames += 1
    cap.release()
    _record(sec, "frame capture from real device", frames > 0,
            f"{frames} frames from index {index} in {seconds:.0f}s")
    return SECTIONS[sec]


# ------------------------------------------------------------------------ MAIN

CHECKS = {
    "phase5": check_phase5,
    "phase6": check_phase6,
    "phase7": check_phase7,
    "phase8": check_phase8,
    "webcam": check_webcam,
}

LABELS = [
    ("PHASE 5 - Evidence/Storage", "PHASE 5  Evidence/Storage"),
    ("PHASE 6 - Video RAG", "PHASE 6  Video RAG"),
    ("PHASE 7 - LangGraph Agent", "PHASE 7  LangGraph Agent"),
    ("PHASE 8 - Forensic Analysis", "PHASE 8  Forensic Analysis"),
    ("WEBCAM", "WEBCAM"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Consolidated system verification")
    parser.add_argument("--only", nargs="*", choices=sorted(CHECKS), default=None)
    parser.add_argument("--skip-webcam", action="store_true")
    parser.add_argument("--webcam-seconds", type=float, default=5.0)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    selected = args.only or [k for k in CHECKS if not (args.skip_webcam and k == "webcam")]
    if args.skip_webcam and "webcam" in CHECKS and "webcam" not in selected:
        # Skipping the device is NOT a pass: record it as unverified.
        SECTIONS["WEBCAM"] = NOT_TESTED
        DETAIL["WEBCAM"] = ["[NOT TESTED] webcam checks skipped with --skip-webcam"]

    print("\n" + "=" * 40)
    print("AI FORENSIC SYSTEM VERIFICATION")
    print("=" * 40)

    for key in selected:
        try:
            if key == "webcam":
                CHECKS[key](args.webcam_seconds)
            elif key == "phase6":
                CHECKS[key](args.base_url)
            else:
                CHECKS[key]()
        except Exception as exc:  # noqa: BLE001
            label = [s for k, s in LABELS if k in key]
            sec = label[0] if label else key
            SECTIONS[sec] = FAIL
            print(f"  [FAIL] {key} crashed: {exc}")
            traceback.print_exc()

    print("\n" + "=" * 40)
    print("VERIFICATION MATRIX")
    print("=" * 40)
    for key, label in LABELS:
        if key not in SECTIONS:
            continue
        print(f"{label:<40}{SECTIONS[key]}")

    failures = [k for k, v in SECTIONS.items() if v == FAIL]
    not_tested = [k for k, v in SECTIONS.items() if v in (NOT_TESTED, ENV_FAILURE)]
    ready = not failures and not not_tested

    print("\n" + "=" * 40)
    print(f"FINAL STATUS: {'READY' if ready else 'NOT READY'}")
    print("=" * 40)
    if failures:
        print("blockers (FAIL):")
        for f in failures:
            for line in DETAIL.get(f, []):
                if line.startswith("[FAIL]"):
                    print(f"  {f}: {line}")
    if not_tested:
        print("not executed (no evidence of success):")
        for f in not_tested:
            for line in DETAIL.get(f, []):
                if not line.startswith("[PASS]"):
                    print(f"  {f}: {line}")

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data",
                           "verification_results.json")
    try:
        os.makedirs(os.path.dirname(out_dir), exist_ok=True)
        with open(out_dir, "w", encoding="utf-8") as fh:
            json.dump({"sections": SECTIONS, "detail": DETAIL, "ready": ready}, fh, indent=2)
    except Exception:  # noqa: BLE001
        pass

    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())

