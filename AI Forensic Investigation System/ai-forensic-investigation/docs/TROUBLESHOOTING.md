# TROUBLESHOOTING.md — common issues and fixes

## 1. Test suite / evaluation

**Q: `tests/test_evaluation.py` fails — benchmark dataset missing.**
A: The 11-scenario fixture is `data/evaluation/benchmark.jsonl`. If absent,
rerun the checkout/recreate it (required keys: `scenario_id`, `category`,
`query`, `expected_event`, `start_time`, `end_time`, `relevant_clips`,
`expected_answer`, `policy_reference`).

**Q: `pytest -q` count line looks garbled on Windows.**
A: The progress line uses `\r`; piping to a file merges it. Read the captured
file like a binary stream (split on `\r`) or run in a real terminal.

## 2. Live sessions

**Q: `429 Too Many Requests` on login.**
A: Credential rate limiting (`LOGIN_RATE_LIMIT_*`). Wait for the window (60s
default) or restart the backend to clear in-process buckets.

**Q: `droidcam_usb` transport fails to start.**
A: OpenCV not installed, or the device index is wrong; DroidCam on Windows
usually exposes index 0. Verify in Python:

```python
import cv2
cap = cv2.VideoCapture(0)
print(cap.isOpened())
```

Set `DROIDCAM_DEVICE_INDEX` if a different device is the capture target.

**Q: WebRTC never connects with the phone.**
A: Both devices must reach the backend. On the same LAN, host candidates are
enough; across NAT, configure `WEBRTC_ICE_SERVERS` (STUN/TURN). Check the
signaling socket (`/live/cameras/{id}/ws/signaling`) for errors.

## 3. Backends (/health shows less than you expected)

**Q: `/health` reports `qdrant: in-memory fallback`.**
A: Qdrant is unreachable. Start it (or accept the deterministic fallback —
results are clearly labeled). Vector search still works in memory.

**Q: `/health` storage says `backend=local`.**
A: MinIO is unreachable or `USE_LOCAL_STORAGE=true`; objects go to
`data/storage/`. This is fully functional for the demo.

**Q: `/health` database fails.**
A: `DATABASE_URL` points at an unreachable PostgreSQL. If none is running, the
cleanest demo path is `reset_demo_database.py` against a fresh Postgres, or the
SQLite test mode used by the pytest suite.

## 4. Reset / backup

**Q: `reset_demo_database.py` needs a target.**
A: Resolution order: `--url` → `DATABASE_URL` env → `backend/.env`. PostgreSQL
is required for the full reset (SQLite is dropped+recreated but not seeded for
a full demo; use `--no-seed` flag intentionally).

**Q: `backup_database.py` fails with “pg_dump not found”.**
A: Install PostgreSQL client tools or set `PG_DUMP=/path/to/pg_dump`. On
Windows use `--no-compress` unless `gzip` is on PATH.

## 5. Frontend

**Q: `npm run dev` can't reach the API.**
A: `NEXT_PUBLIC_API_URL` must match the backend origin (default
`http://127.0.0.1:8000`); CORS must include the frontend origin
(`BACKEND_CORS_ORIGINS`).

**Q: Build is slow / next lint fails on stale `.next`.**
A: Remove `frontend/.next`, `tsconfig.tsbuildinfo`, then rebuild
(`npm run build`).

## 6. Storage / the audit trail

**Q: Evidence shows `index_status=FAILED`.**
A: The indexer retries up to `EVIDENCE_INDEX_MAX_ATTEMPTS` with backoff; rows
marked FAILED are never silently dropped. Inspect backend logs, fix the vector
backend, then resubmit:

```bash
python scripts/verify_evidence_integrity.py --resubmit-failed
```

**Q: Where is the audit log?**
A: `audit_logs` table records user_register/login/logout, live session
start/stop, VLM analyzes, investigations, analysis runs and report generation.