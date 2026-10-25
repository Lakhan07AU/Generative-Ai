# PHASE 9 - SYSTEM AUDIT

Date: 2026-09-12
Scope: Full read-only audit of the AI Forensic Investigation System performed before the Phase 9 production-hardening pass. Every finding below was verified directly against the repository (source tree, migrations, config, tests, container definitions). No changes were made during the audit.

Severity scale:
- **CRITICAL** - blocks a credible production deployment or enables clear abuse.
- **HIGH** - serious in production; acceptable only in a labelled demo.
- **MEDIUM** - should be fixed for robustness / correctness across environments.
- **LOW** - hygiene / documentation / polish.
- **INFO** - observation, no action required.

---

## 1. Repository structure

| Area | State | Severity |
|---|---|---|
| `backend/app` (28 subpackages) | Clean layering: api / auth / ai / detection / tracking / vlm / evidence / live / investigator / forensic / storage / report / rag / agents | INFO |
| `frontend/app` (19 screens) | login, register, dashboard, live, videos, evidence, search, investigations, reports, policies, demo, settings, runs | INFO |
| `tests/` (39 test files) | Good coverage per phase; 6 failures are the missing evaluation fixture (see §8) | MEDIUM |
| `scripts/evaluate.py` | Deterministic offline evaluation harness (fixed seeds), not a live-system benchmark | INFO |
| Alembic migrations | 8 linear revisions `0001_initial` → `0008_phase8_forensics`; head applied to live Postgres | INFO |
| Backend models | 28 models; Phase 8 block (`ForensicTimelineEvent` / `ForensicAnalysis` / `FindingReview` / `ForensicReport`) correct incl. `extra_metadata` mapped to `metadata` | INFO |
| Docker / compose | Dev-oriented (`--reload`, `npm run dev`, bind mounts) - finalised in this phase | MEDIUM |
| `.gitignore` | Covers `.env`, `*.env`, `data/` (with `!data/evaluation/benchmark.jsonl`), `node_modules/`, `.next/`, `models/*.pt`, caches | INFO |

### Generated artifacts present on disk (not source)
- `backend/local_forensics.db` - stale SQLite database left over from earlier local runs; must be removed and excluded.
- `backend/uvicorn*.log` (4 files), `frontend/next.log`, `frontend/next_err.log`.
- `frontend/.next/`, `frontend/node_modules/`, `__pycache__/`, `.pytest_cache/`, `tsconfig.tsbuildinfo` (build outputs - regenerable).

---

## 2. Secrets, configuration, dead code

| Finding | Location | Severity |
|---|---|---|
| `SECRET_KEY` defaults to `"change_me"` | `backend/app/core/config.py:13` | CRITICAL (prod) |
| `.env` / `backend/.env` carry a dev-only placeholder secret | `dev_secret_key_for_local_testing_only_change_in_production` | HIGH (prod), OK (demo) |
| Demo passwords hardcoded in seed + verify scripts (`demo-investigation-2026`, `DemoAdmin123!`) | only `backend/scripts/*.py` | INFO (demo-labelled, never production creds) |
| No login rate limiting / account lockout | `backend/app/api/auth.py:40` | HIGH (prod), MEDIUM (demo) |
| Dead flag `USE_LOCAL_STORAGE = True` | `backend/app/storage/service.py:10` | LOW |
| `MINIO_PUBLIC_ENDPOINT` documented in `.env.example` but unused by config | `.env.example:25` | LOW |
| `.env.example` is out of sync with `Settings` (missing `MINIO_BUCKET_REPORTS`, `FORENSIC_*`, Phase 3-5 vars, `DATABASE_URL` local vs compose) | `.env.example` vs `config.py` | MEDIUM |
| No TODO / FIXME / `NotImplementedError` anywhere in `backend/` | grep sweep | INFO (clean) |

Note: role checks read the **database** user role (`get_current_user`), never the JWT `role` claim, so a forged `role` claim is not trusted. Verified in `backend/app/auth/deps.py:38-46`.

---

## 3. Storage & vector store availability honesty

| Finding | Location | Severity |
|---|---|---|
| MinIO outage silently falls back to local filesystem - **no indication of which backend is in use** | `backend/app/storage/service.py:74-151` | HIGH |
| Qdrant outage silently falls back to in-memory cosine store - `_backend` is private, no status accessor | `backend/app/ai/qdrant_service.py:99-127` | HIGH |
| `/health` returns `{"status": "ok"}` only - no component detail | `backend/app/main.py:60-62` | HIGH |
| Evidence `index_status` is honest (PENDING → INDEXING → INDEXED | FAILED), bounded queue (64) with drop-oldest, retries with backoff, and a `reindex` API | `backend/app/evidence/indexer.py`, `backend/app/api/evidence_live.py:162` | INFO (good) |
| Embedding dimension is guarded: indexer rejects vectors whose length != collection dimension | `backend/app/evidence/indexer.py:198` | INFO (good) |

---

## 4. AI provider & anti-hallucination baseline (already strong)

| Finding | Location |
|---|---|
| Provider is simulation-by-default and always labels output `[SIMULATED]`; real mode = any OpenAI-compatible endpoint | `backend/app/ai/provider.py` |
| VLM prompts forbid identity/intent inference and facial/biometric identification | `provider.py:242-290` |
| Structured VLM JSON is normalized/validated (`OBSERVED`/`INFERRED`/`UNKNOWN`, confidence clamped 0-1) | `provider.py:312-355` |
| Only `[OBSERVED]` statements may surface as grounded text (`is_observed_statement`) | `backend/app/investigator/tools.py:59` |
| Evidence text is sanitized/truncated before surfacing (untrusted-input discipline) | `tools.py:50` |
| Bounded agent guardrails (steps / tool calls / evidence / seconds) are enforced per run | `config.py` (AGENT_MAX_*), `investigator/` |
| Contradictions are detected and reported, never "resolved" by the agent | `tools.py:253` |
| YOLO model cached per config + inference serialized under per-engine lock; `torch>=2.6` loading patched | `backend/app/detection/engine.py:1-80` |
| Live pipeline queues are bounded with drop-oldest: detection (8), VLM (per-session, rate-limited), evidence index (64), subscriber WS (64) | `detection/worker.py`, `vlm/queue.py`, `evidence/indexer.py`, `live/manager.py` |

---

## 5. Live camera / DroidCam

| Finding | Location | Severity |
|---|---|---|
| Transports are only `webrtc`, `simulation`, `file` - **no USB / IP / DroidCam source** | `backend/app/api/live.py:124-126` | HIGH (required deliverable) |
| `LiveCameraSource` is a push-adapter only (no `connect`/`read_frame`/`is_alive`/`health`) | `backend/app/live/source.py` | HIGH (required deliverable) |
| `VideoFileFeeder` is the OpenCV-capture template (daemon thread, fps pacing) - basis for `DROIDCAM_USB` | `backend/app/live/video_feeder.py:74-104` | INFO |
| File transport already guards path traversal (realpath must be under `DEMO_DATA_DIR`) | `backend/app/api/live.py:135-142` | INFO (good - reuse pattern) |
| Manager guarantees at most one active session per camera; subscriber queues bounded (64); thread-safe publish | `backend/app/live/manager.py` | INFO (good) |
| All live WebSockets require a first-message JWT + `LIVE_ROLES` | `backend/app/api/live.py:230-250` | INFO (good) |

---

## 6. Frontend

| Finding | Location | Severity |
|---|---|---|
| 19 screens present; live page hosts cameras + detection + tracking + VLM panels | `frontend/app/` | INFO |
| **No audit-trail viewer** in the UI (audit rows exist server-side) | `backend/app/audit/service.py`, no frontend page | LOW |
| **No dedicated cameras admin page** (camera CRUD lives in live/settings) | `frontend/app` | LOW |
| JWT stored in `localStorage` (XSS surface); standard for this app, worth documenting | `frontend/lib/api.ts:977-1004` | LOW |
| `BACKEND_CORS_ORIGINS` defaults permissive `*` methods; restrictable in `.env` | `config.py:33`, `main.py:29-35` | LOW |
| TypeScript compiles clean (`npx tsc --noEmit` → exit 0) | - | INFO |

---

## 7. Evaluation harness

| Finding | Severity |
|---|---|
| 6 failing tests (`test_evaluation.py`) are **entirely** caused by the missing `data/evaluation/benchmark.jsonl` fixture (they also `import evaluate` and test pure metric math, which is unit-correct) | MEDIUM |
| The harness is a deterministic offline simulation (fixed seeds), *by design* self-contained; it is unit-verifiable metric math, **not** a live-system benchmark - this will be reported honestly in Phase 9 | INFO |
| Fix: generate the 11-scenario fixture in the exact schema asserted (`scenario_id, category, query, expected_event, start_time, end_time, relevant_clips, expected_answer, policy_reference`, 11 distinct categories incl. `no_matching_event` with empty clips) | HIGH (restores green suite) |

---

## 8. Observability, deployments, backups

| Finding | Severity |
|---|---|
| No Prometheus / `/metrics` / structured telemetry endpoint (only per-session counters) | MEDIUM |
| No backup / recovery scripts (postgres dump, MinIO mirror) | MEDIUM |
| Docker backend command runs `uvicorn --reload`; frontend runs `npm run dev` (dev defaults) | MEDIUM |
| No resource limits in compose; qdrant pinned `v1.9.4`, other images `latest` | LOW |

---

## 9. Audit-verified good practice (kept as-is)

- Reports are versioned; regenerating appends a new version and never deletes prior ones (`forensic_reports.version`).
- Original evidence is immutable: uploaded media is never rewritten, evidence frames are copy-encoded derivatives (`evidence/paths.py`, MinIO object-lock comment in `models.py`).
- Every evidence record carries server-generated provenance (`ForensicEvidence.provenance`), byte-identity hash (`sha256`) and honest index state.
- Human review entries snapshot the reviewed content (`FindingReview.finding_snapshot`) so review is auditable after regeneration.
- Audit log records login/logout/agent/tool/verification/timeline/live-session/report events (`app/audit/service.py`).
- Simulation is deterministic and impossible to mistake for a real model result (`[SIMULATED ...]` prefixes).

---

## 10. Phase 9 action register (built from the above)

| # | Action | Severity | Deliverable |
|---|---|---|---|
| 1 | Detailed `/health` (db, storage backend + ok, qdrant backend + ok, llm, embedding, live sessions, evidence indexer) | CRITICAL | `main.py`, `storage/service.py`, `qdrant_service.py` |
| 2 | `DROIDCAM_USB` camera source + `CameraSource` abstraction | HIGH | `live/source.py`, `live/droidcam.py`, `api/live.py` |
| 3 | Secret handling: gen-in-place dev secret check, `.env.example` resync, document rotation | HIGH | `.env.example`, `SECURITY.md` |
| 4 | Login rate limiting | HIGH | `api/auth.py` |
| 5 | `reset_demo_database.py` (Postgres default, clean seed) | HIGH | `backend/scripts/` |
| 6 | `verify_evidence_integrity.py` (sha256/blobs/orphans/index sync) | HIGH | `backend/scripts/` |
| 7 | `verify_demo_dataset.py` | HIGH | `backend/scripts/` |
| 8 | `run_full_e2e.py` (auto-detect + skip w/ `NOT TESTED — DEPENDENCY UNAVAILABLE`) | HIGH | `backend/scripts/` |
| 9 | Fix `test_evaluation.py` via benchmark fixture | HIGH | `data/evaluation/benchmark.jsonl` |
| 10 | Security / anti-hallucination / clean-start tests | HIGH | `tests/` |
| 11 | Frontend: audit-trail viewer + DroidCam live controls + prod build | MEDIUM | `frontend/app/` |
| 12 | Backups + operations | MEDIUM | `backend/scripts/`, `OPERATIONS.md` |
| 13 | Compose/Docker production-ise | MEDIUM | `docker-compose.yml`, `Dockerfile`s |
| 14 | Docs (`ARCHITECTURE`, `DEMO_GUIDE`, `TROUBLESHOOTING`, `SECURITY`, `OPERATIONS`, README) | MEDIUM | root docs |
| 15 | Performance + test matrix + final report + verdict | HIGH | `PHASE9_*` |

Generated artifacts cleaned at the end of the phase: `backend/local_forensics.db`, `backend/uvicorn*.log`, `frontend/next*.log`, caches.

## 11. Verdict (risk statement, before the Phase 9 work)

The system is functionally complete across Phases 1-8 and the demonstration workflow (upload → process → detect → track → VLM → evidence → investigate → verify → review → report) is working against the live stack. The audit found **no CRITICAL defects in the demo configuration** itself; the CRITICAL/HIGH items above are production-readiness gaps (secret hygiene, availability honesty, login rate limiting, camera-source abstraction, missing fixtures/scripts). The final Phase 9 verdict will be issued only after those items are implemented and verified.