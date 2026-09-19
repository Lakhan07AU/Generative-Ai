# OPERATIONS.md — Phase 9 operational hardening

Day-to-day operations for the AI Forensic Investigation System demo stack.

## 1. Services and ports

| Service   | Port      | Notes                                              |
|-----------|-----------|----------------------------------------------------|
| PostgreSQL | 5432     | main evidence + analytics database                  |
| Qdrant    | 6333      | vector store (video_evidence, policy_chunks)        |
| MinIO     | 9000      | optional S3 object store (local FS fallback works)  |
| Backend   | 8000      | FastAPI (`app/main.py`)                             |
| Frontend  | 3000      | Next.js 14 (`frontend/`)                            |

The backend transparently falls back when Qdrant/MinIO are unreachable: vector
search uses a deterministic in-memory store, objects use the local filesystem.
`/health` reports which backend is actually in use.

## 2. Quick start (local, without containers)

1. Install backend requirements (`pip install -r requirements.txt`, Python 3.11)
   and start PostgreSQL + Qdrant, or rely on the fallbacks.
2. Run migrations and seed the demo:

   ```bash
   cd backend
   python scripts/reset_demo_database.py          # drop + Alembic head + seed
   python -m uvicorn app.main:app --reload --port 8000
   ```

3. Frontend: `cd frontend && npm install && npm run dev` (http://localhost:3000).

## 3. Reset / clean start

`reset_demo_database.py` reproduces the demo backend in one step:

1. Drops/recreates the schema (PostgreSQL) or deletes the SQLite file.
2. Runs `alembic upgrade head` (migration head is `0008`).
3. Clears Qdrant collections and stored objects.
4. Re-seeds the DEMO-PHASE6 forensic evidence set (users, camera, video,
   investigation, forensic evidence + vector points).

```bash
cd backend
python scripts/reset_demo_database.py
python scripts/reset_demo_database.py --url postgresql+psycopg2://user:pw@host:5432/forensics
python scripts/reset_demo_database.py --no-seed          # schema only
python scripts/reset_demo_database.py --no-clear-storage # keep object store
```

`--dry-run` style safety: the script only touches the resolved target database
and DEMO-named resources; it never creates non-demo data.

## 4. Backups and restore

```bash
cd backend
python scripts/backup_database.py              # pg_dump -> backups/*.sql(.gz)
python scripts/backup_database.py --no-compress
python scripts/backup_database.py --out ../backups
```

* PostgreSQL: streams `pg_dump` (discovered from PATH or `PG_DUMP`).
* SQLite: copies the database file (safe because it is file-backed).

Restore (PostgreSQL):

```bash
psql "$DATABASE_URL" -f backups/forensics-<timestamp>.sql
```

Stored media lives separately (MinIO buckets or `data/storage/`); back it up the
same way you back up any object storage / directory.

## 5. Verification scripts

Run from `backend/`:

| Script | Purpose |
|--------|---------|
| `verify_demo_dataset.py` | physical dataset + benchmark + stale artifacts |
| `verify_evidence_integrity.py` | evidence ledger vs storage vs vector index (sha256 / orphan / index sync); `--resubmit-failed` re-queues PENDING/FAILED |
| `verify_demo_investigation.py` | full demo dataset + workflow, `--base-url` for a real live run |
| `run_full_e2e.py` | full end-to-end demo (dependency-gated); `--reset-db`, `--with-agents`, `--base-url` |

Each exits non-zero on a required FAIL. `run_full_e2e.py` reports
`NOT TESTED - DEPENDENCY UNAVAILABLE` for skipped stages so results are honest.

## 6. Observability

* `GET /health` — per-component status (database, qdrant, storage,
  evidence_indexer, live sessions). Top level `ok`/`degraded`.
* `GET /metrics` — Prometheus-text gauges (evidence indexer, live sources,
  session count, backend flags) with no extra dependencies.

## 7. Security checklist

* Rotate `SECRET_KEY` (the backend logs a startup warning while a known dev
  default is set).
* Login is rate-limited per IP+email (sliding window,
  `LOGIN_RATE_LIMIT_*`); the demo default is 5 attempts / 60s.
* Cameras/live endpoints are role-gated (`ADMIN`, `SECURITY_OFFICER`,
  `INVESTIGATOR`) with role checks against the DB, never the JWT claim.
* The `file` live transport only accepts `video_path` under `DEMO_DATA_DIR`.
* No facial recognition or biometric identification is performed anywhere.

## 8. Known dev defaults (acceptable for the demo only)

* `SECRET_KEY=dev_secret_key_for_local_testing_only_change_in_production`
* `LLM_PROVIDER=simulation`, `WHISPER_MODEL=simulation` (deterministic offline
  providers)
* `USE_LOCAL_STORAGE=true` local filesystem instead of MinIO