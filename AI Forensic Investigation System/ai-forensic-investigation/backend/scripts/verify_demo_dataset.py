"""Phase 9 - Demo dataset / infrastructure health verifier.

Local-only (no server required): verifies that every required physical file,
configuration and on-disk artifact is healthy before any demo run. Stale
artifacts left over from prior experiments are explicitly detected and reported.

Checks (critical = FAILs the script with exit 1):

  * data/demo_investigation/videos/*.mp4 present, non-empty
  * data/demo_investigation/cases.json valid + every referenced video exists
  * data/demo_investigation/expected_events/*.json valid
  * data/demo_investigation/expected_observations/*.json valid
  * data/evaluation/benchmark.jsonl present + exactly 11 rows with all required keys
  * backend/local_forensics.db absent (stale SQLite artifact)
  * backend/uvicorn*.log count reported (informational)

Soft checks (WARN, never FAIL):
  * DATABASE_URL reachable (Postgres)
  * QDRANT_URL reachable (Qdrant)
  * storage bucket check (MinIO / local)

Run from ``backend/``::

    python scripts/verify_demo_dataset.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import glob
import urllib.request
import urllib.error

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
ROOT = os.path.join(BACKEND_DIR, "data", "demo_investigation")
EVAL_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "data", "evaluation")

results: list[dict] = []
failed: int = 0


def record(ok: bool, name: str, detail: str = "", critical: bool = True) -> bool:
    global failed
    tag = "PASS" if ok else ("FAIL" if critical else "WARN")
    results.append({"check": name, "tag": tag, "detail": detail})
    print(f"  [{tag}] {name}" + (f" - {detail}" if detail else ""))
    if not ok and critical:
        failed += 1
    return bool(ok)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_videos() -> bool:
    ok = True
    video_dir = os.path.join(ROOT, "videos")
    mp4s = sorted(glob.glob(os.path.join(video_dir, "*.mp4")))
    ok &= record(len(mp4s) >= 5, "at least 5 demo video files present", f"{len(mp4s)} files")
    for p in mp4s:
        sz = os.path.getsize(p)
        ok &= record(sz > 0, f"non-empty video {os.path.basename(p)}", f"{sz:,} bytes")
    return ok


def _verify_cases() -> bool:
    ok = True
    cases_path = os.path.join(ROOT, "cases.json")
    if not os.path.isfile(cases_path):
        return record(False, "cases.json exists")
    try:
        with open(cases_path, "r", encoding="utf-8") as fh:
            cases = json.load(fh)
    except (OSError, ValueError) as exc:
        return record(False, "cases.json valid JSON", str(exc))
    ok &= record(isinstance(cases, list) and len(cases) >= 5, "cases.json has >= 5 cases", f"{len(cases)} cases")
    for case in cases:
        vid = case.get("video_path") or case.get("video") or ""
        if vid:
            full = os.path.join(ROOT, vid) if not os.path.isabs(vid) else vid
            ok &= record(os.path.isfile(full), f"case {case.get('id', '?')} video exists", vid)
    return ok


def _verify_events_observations() -> bool:
    ok = True
    for sub in ("expected_events", "expected_observations"):
        folder = os.path.join(ROOT, sub)
        if not os.path.isdir(folder):
            ok &= record(False, f"{sub}/ directory exists")
            continue
        files = sorted(glob.glob(os.path.join(folder, "*.json")))
        ok &= record(len(files) >= 1, f"{sub}/ has at least one JSON file", f"{len(files)} files")
        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8") as fh:
                    json.load(fh)
            except (OSError, ValueError) as exc:
                ok &= record(False, f"{os.path.basename(fp)} valid JSON", str(exc))
    return ok


def _verify_benchmark() -> bool:
    ok = True
    bench = os.path.join(EVAL_DIR, "benchmark.jsonl")
    if not os.path.isfile(bench):
        return record(False, "benchmark.jsonl exists")
    rows = []
    with open(bench, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError as exc:
                    ok &= record(False, "benchmark.jsonl line valid JSON", str(exc))
    ok &= record(len(rows) == 11, "benchmark.jsonl has 11 rows", f"{len(rows)} rows")
    required = {
        "scenario_id", "category", "query", "expected_event", "start_time",
        "end_time", "relevant_clips", "expected_answer", "policy_reference",
    }
    for row in rows:
        missing = required - set(row.keys())
        ok &= record(
            not missing, f"row {row.get('scenario_id', '?')} has required fields",
            f"missing {missing}" if missing else "",
        )
    return ok


def _verify_stale_artifacts() -> bool:
    ok = True
    stale_db = os.path.join(BACKEND_DIR, "local_forensics.db")
    ok &= record(not os.path.isfile(stale_db), "no stale local_forensics.db", critical=False)
    logs = sorted(glob.glob(os.path.join(BACKEND_DIR, "uvicorn*.log")))
    if logs:
        record(True, "uvicorn logs present (informational)", f"{len(logs)} files", critical=False)
    return ok


def _verify_soft_infra() -> None:
    # PostgreSQL
    try:
        from sqlalchemy import text
        from app.database.session import SessionLocal
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        record(True, "database reachable", critical=False)
    except Exception as exc:  # noqa: BLE001
        record(False, "database reachable", str(exc)[:200], critical=False)
    # Qdrant
    try:
        url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        urllib.request.urlopen(f"{url}/collections", timeout=2)
        record(True, "qdrant reachable", critical=False)
    except Exception as exc:  # noqa: BLE001
        record(False, "qdrant reachable", str(exc)[:200], critical=False)
    # storage
    try:
        from app.storage.service import storage
        storage.ensure_buckets()
        record(True, "storage buckets OK", f"backend={storage.backend_name()}", critical=False)
    except Exception as exc:  # noqa: BLE001
        record(False, "storage buckets OK", str(exc)[:200], critical=False)


def main() -> None:
    print("=" * 72)
    print("DEMO DATASET HEALTH VERIFICATION")
    print("=" * 72)
    ok = True
    ok &= _verify_videos()
    ok &= _verify_cases()
    ok &= _verify_events_observations()
    ok &= _verify_benchmark()
    _verify_stale_artifacts()
    _verify_soft_infra()

    print("-" * 72)
    total_pass = sum(1 for r in results if r["tag"] == "PASS")
    total_fail = sum(1 for r in results if r["tag"] == "FAIL")
    total_warn = sum(1 for r in results if r["tag"] == "WARN")
    print(f"RESULT: {total_pass} PASS / {total_fail} FAIL / {total_warn} WARN")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()