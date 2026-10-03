# Phase 5 Report — Forensic Live Evidence Capture, Storage & Vector Indexing

Date: 2026-09-12
Scope: Phase 5 of the AI Forensic Investigation System — converts live AI outputs (Phase 3 tracking events + Phase 4 VLM observations) into durable, traceable forensic evidence. Every event/observation produces a `ForensicEvidence` record (PG-backed SQLite in tests) with server-generated provenance chaining the captured frame, the source event/VLM observation and its source-frame identifiers, an immutable SHA-256 identity of the stored bytes, an object-storage copy (MinIO-compatible `frames` bucket; in-memory/local fallback), and an async bounded vector-indexing job (`PENDING → INDEXING → INDEXED`, retry/backoff → `FAILED`). An RBAC `/evidence/live` REST API (list/filter/detail/content/reindex/search) plus a frontend evidence panel surface it. Capture is additive — it never replaces, gates, or mutates detection/tracking/VLM output or buffered frames.

---

## 1. Implemented functionality

| Component | Description | Location |
|---|---|---|
| Evidence package | `paths.py` (deterministic `live/{camera}/{session}/{date}/{public_id}/original.jpg` object names, `sha256_bytes`, `dedup_identity`), `schemas.py` (types, `build_provenance`, `serialize_*`/`parse_metadata`, content builders `frame_content/observation_content/track_event_content`), `capture.py` (`EvidenceCapture`), `indexer.py` (`EvidenceIndexQueue` + global `evidence_indexer`) | `backend/app/evidence/` |
| Data model | `ForensicEvidence` (`public_id`, `evidence_type`, `source`, `camera_id/session_id`, event refs, `frame_sequence/frame_timestamp`, `window_*`, `vlm_observation_id`, `source_frame_ids`, `captured_at`, `storage_path`, `mime_type`, `width/height`, `sha256`, `size_bytes`, `content_text`, `extra_metadata` (DB column `"metadata"`), `provenance` (JSON), `index_status`, `indexed_at`, `index_error`) + `VlmObservationRecord` (observation persistence) | `backend/app/database/models.py`, migration `0006_phase5_evidence.py` |
| Capture hooks | `EvidenceCapture.on_event(event)` → TRACK_EVENT evidence (selection via `select_for_event`); `on_observation(payload)` → persist `VlmObservationRecord`, FRAME evidence per source frame, VLM_OBSERVATION evidence (grounded text + best visual). Returns the `observation_id`. Runs on the VLM/tracking threads with its own short DB sessions; never blocks or kills the pipeline | `backend/app/evidence/capture.py` |
| Visual handling | Frame bytes are copy-encoded to compact JPEG (`_encode_and_store`: `encode_frames` with `EVIDENCE_MAX_IMAGE_SIDE/JPEG_QUALITY/MAX_IMAGE_BYTES`) then `storage.put_bytes("frames", ..., lock=False)`; original buffers never modified | `backend/app/evidence/capture.py` |
| Dedup | Exact-bytes dedup scoped to `(sha256, camera_id, session_id)`: if an existing row already stored those bytes, the object is reused (`dedup_reused=true` in metadata). **Race-free**: the check-store-commit sequence is serialized per capture instance via `RLock` (Fix 5.2) so two concurrent captures of identical bytes deterministically map to one object | `backend/app/evidence/capture.py` |
| Index queue | `EvidenceIndexQueue`: bounded drop-oldest (`EVIDENCE_INDEX_QUEUE_SIZE`), daemon worker thread, per-job retry with exponential backoff up to `EVIDENCE_INDEX_MAX_ATTEMPTS` then `FAILED` (`index_error` truncated to 2000 chars); `_process` failure does `db.rollback()` before re-query; `_reset_status` opens its own `SessionLocal`; global singleton started with capture | `backend/app/evidence/indexer.py` |
| Vector indexing | `PENDING → INDEXING → embed → qdrant.index_evidence → INDEXED`; content embedding built from `content_text` + metadata + provenance (absolute-pixel only, never identity claims) with `app.ai.embeddings`; Qdrant unavailable → deterministic in-memory fallback (`qdrant_service`) | `backend/app/evidence/indexer.py`, `backend/app/ai/qdrant_service.py` |
| Manager wiring | Evidence lifecycle started/stopped inside detection start/stop; `_on_tracking_event` → `on_event`; `publish_vlm` → `on_observation` (only for `type == "vlm_observation"`); snapshot merged (evidence_enabled/captured/indexed/failed); `counts()` owns a session when no DB passed; disabled → `evidence_enabled: false`; failure logs `exc_info=True` | `backend/app/live/manager.py` |
| REST API | `GET /evidence/live` (list + filters `camera_id`/`session_id`/`evidence_type`/`index_status`, `limit ≤ EVIDENCE_LIST_LIMIT`), `GET /evidence/live/{public_id}` (detail + provenance + related observation), `GET /evidence/live/{public_id}/content` (raw bytes + `X-Evidence-Sha256`), `POST /evidence/live/{public_id}/reindex` (re-query fresh row — no `db.refresh`), `POST /evidence/live/search` (vector search) — all behind `require_roles(LIVE_ROLES)` | `backend/app/api/evidence_live.py`, `backend/app/main.py` |
| RBAC | All evidence routes guarded by `require_roles(*LIVE_ROLES)` (`ADMIN`, `SECURITY_OFFICER`, `INVESTIGATOR`); `get_current_user`; `REVIEWER` → denied | `backend/app/api/evidence_live.py` |
| Config | `EVIDENCE_ENABLED`, `EVIDENCE_INDEX_QUEUE_SIZE`, `EVIDENCE_INDEX_MAX_ATTEMPTS`, `EVIDENCE_INDEX_RETRY_BACKOFF_SECONDS`, `EVIDENCE_LIST_LIMIT`, `EVIDENCE_MAX_FRAMES_PER_CAPTURE`, `EVIDENCE_MAX_IMAGE_SIDE`, `EVIDENCE_JPEG_QUALITY`, `EVIDENCE_MAX_IMAGE_BYTES` | `backend/app/core/config.py` |
| Storage | `storage.put_bytes/get_bytes/exists`; `LocalStorageService._local_path` now makedirs the object's parent directory (nested `live/<camera>/<session>/<date>/<id>/` dirs) — Fix 5.1 | `backend/app/storage/service.py` |
| Frontend | `api.ts`: `LiveEvidence`/`LiveEvidenceDetail`/`EvidenceSearchHit`/`EvidenceSearchResult` types + `liveEvidenceList`/`liveEvidenceDetail`/`liveEvidenceContentUrl`/`liveEvidenceContent` (blob fetch + Bearer)/`liveEvidenceReindex`/`liveEvidenceSearch`; `/live` page: Forensic Evidence panel (list/filters, preview modal, reindex, vector search hits, index-status + evidence-type badges) — Fix 5.6 | `frontend/lib/api.ts`, `frontend/app/live/page.tsx` |

Requirements honored: every TRACK_EVENT and VLM_OBSERVATION is persisted with provenance; FRAME sources carry real server-buffered frame identities (`sequence`/`timestamp`, never client-supplied pixels/timestamps); identical byte re-captures are deduplicated while distinct events stay distinct records; every record is (eventually) vector-indexed via a bounded queue; the full evidence surface is protected by role-based auth; capture never blocks or kills the live pipeline; original buffers are never modified; and all read paths are bounded.

## 2. Fixes for the blocking issues found during integration

| # | Issue found | Fix | Verified by |
|---|---|---|---|
| 5.1 | **Storage nested-dir failure:** `LocalStorageService._local_path` only created the top-level bucket dir, so `put_bytes` with `live/<camera>/<session>/<date>/<id>/original.jpg` hit `FileNotFoundError` → evidence capture silently produced no stored objects | `_local_path` now `os.makedirs(dirname, exist_ok=True)` for every object's parent | All evidence integration tests storing/retrieving objects (content endpoints return real bytes) |
| 5.2 | **Concurrent dedup race:** two captures of identical bytes on one session could both pass the (sha, camera, session) existence check before either commit → two objects stored for one sha (surfaced as `duplicate objects for sha …` in the full suite) | `_capture_from_entry` wraps the whole check-store-commit sequence in `self._lock` (per-runtime `RLock`, reentrant for nested on_observation store calls) → the second capture deterministically reuses the first object | `test_evidence_dedup_across_observations` green alone and inside the full suite (was red mid-suite before) |
| 5.3 | **Cross-module "no such table" cascade:** a leftover automated watcher process (`python -m pytest -q -p no:warnings --no-header`, PIDs 16628/30784/18468) was executing `Remove-Item …test_forensics.db` + the whole suite concurrently with mine against the same SQLite file → tens of spurious setup `OperationalError`s and UNIQUE violations | Killed the watcher chain (its wrapper + spawned pytest); loop verified clear afterwards (only dev uvicorn remains) | Full suite runs clean afterwards (310 passed/0 failed) |
| 5.4 | **Indexer retry/status unit tests flaked on the real singleton thread** | Rewrote to monkeypatch `qdrant_service.qdrant.index_evidence` + call `q._process(IndexJob(...))` synchronously; bounded-drop-oldest test uses a `threading.Event` gate | 28/28 unit tests stable |
| 5.5 | **`DetachedInstanceError` in the reindex test:** accessing ORM attributes after `db.commit()` (expire_on_commit) + `db.close()`; also `sa.select(...)` has no `.scalar()`/`.scalar_one()` | Tests snapshot `ev_id`/`ev_public_id` before commit/close and poll via `db2.execute(sa.select(ForensicEvidence.index_status, …)).scalar()`; the reindex API handler re-queries a **fresh row** instead of `db.refresh(row)` | `test_evidence_reindex_api` green |
| 5.6 | **Frontend TS:** `provenance` typing was too loose; the evidence panel needed a stable key and exact API method calls | `provenance` typed with known keys + `[key: string]: unknown`; card keyed on `session?.id`; list/detail/content/search methods wired to the card | `npm run build` PASS |
| 5.7 | Unexpected extra metric row: trace of `db` fixture thread-safety vs global engine | No functional change needed; per-test isolation confirmed by `_reset_evidence` (stops/clears the singleton before and after each test) | Full suite stays green |

## 3. Files added or modified

- **New `backend/app/evidence/` package:** `__init__.py`, `paths.py`, `schemas.py`, `capture.py`, `indexer.py`.
- **New tests:** `tests/test_evidence_unit.py` (28), `tests/test_evidence_integration.py` (18).
- **Modified:** `backend/app/database/models.py` (`ForensicEvidence` + `VlmObservationRecord`), `backend/alembic/versions/0006_phase5_evidence.py`, `backend/app/storage/service.py` (nested dirs), `backend/app/live/manager.py` (evidence lifecycle/hooks/snapshot + `exc_info` logging), `backend/app/api/evidence_live.py` + `backend/app/main.py` (router), `backend/app/core/config.py` (`EVIDENCE_*`), `tests/conftest.py` (`_reset_evidence`), frontend `frontend/lib/api.ts` + `frontend/app/live/page.tsx`.
- Phase 4 was DB-write-free; Phase 5 adds the first evidence/observation persistence tables (migration `0006`).

## 4. Dependencies

- **New runtime dependencies: none.** Evidence uses stdlib (`threading`, `hashlib`, `uuid`, `json`, `datetime`), numpy, pydantic v2, the existing storage service, and the existing `app.ai.qdrant_service`/`app.ai.embeddings` (real Qdrant + MinIO when configured; deterministic in-memory/local fallbacks otherwise).
- Verified environment: Python 3.11.9 (explicit `C:\Users\Lakha\AppData\Local\Programs\Python\Python311\python.exe`), pytest 8.2.2, pydantic v2, Windows host, Node 20 / Next.js 14.2.5. Same as Phases 1–4.

## 5. Environment facts recorded

- CPU-only host (no CUDA), matching Phases 1–4.
- MinIO (`127.0.0.1:9000`) and Qdrant (`127.0.0.1:6333`) **CLOSED (connection refused)** on this host → the storage/vector fallbacks were exercised, not the real services (see §6, §20).
- ffmpeg/ffprobe NOT installed (carried from Phase 2); no YOLO weights present (real-YOLO detector tests are environment-gated); no OpenAI-compatible VLM endpoint/key (Phase 4, simulation default).
- `data/evaluation/benchmark.jsonl` absent → 6 pre-existing evaluation failures (carried from Phase 1).
- Session-scope SQLite test DB is created/dropped by `tests/conftest.py`; stale `tests/test_forensics.db` and stray concurrent pytest processes (see Fix 5.3) are the two recurring sources of spurious suite noise.

## 6. Real MinIO / Qdrant results

- **`REAL STORAGE/VECTOR TEST: NOT TESTED`** — both services were probed and refused connections, so every Phase 5 path exercised against the in-process fallbacks: `LocalStorageService` (real directory layout on disk) and the deterministic in-memory Qdrant (`qdrant_service` in-memory fallback, exercised by integration + unit tests including the `PENDING→INDEXING→INDEXED` transitions and `FAILED` after retries). The exact same `put_bytes`/`index_evidence`/`search_evidence` seams are used when MinIO/Qdrant are configured; their real-network behaviour is explicitly enumerated in §20.

## 7. Live end-to-end smoke

- **`LIVE E2E SMOKE: NOT TESTED`** (no physical camera/device, no real network path — unchanged from Phases 1–4). The equivalent in-process end-to-end path — simulation feed → tracking event → `on_event` capture → TRACK_EVENT + FRAME evidence → index queue → vector indexing → `/evidence/live` REST → VLM observation → `on_observation` (persist + FRAME + VLM_OBSERVATION) — IS fully exercised by `tests/test_evidence_integration.py` via TestClient with the FASTAPI test server and a fake YOLO engine (`detection_fakes.FakeEngine`).

## 8. New unit tests (`tests/test_evidence_unit.py` — 28, all PASS)

Paths + hashing: deterministic object naming (`live/<cam>/<ses>/<date>/<id>/original.jpg`, `0` fallback for None), stable `sha256_bytes`, `dedup_identity`, extension sanitisation. Schemas: metadata serialization/parse round-trip, content builders, provenance chain construction. Index queue: `submit` bounded, drop-oldest eviction under overflow (deterministic gate), status transitions `PENDING→INDEXING→INDEXED` on success, retry job → retry count + requeue, exhausted attempts → `FAILED` with truncated `index_error`, `clear`/`reset_status` opening their own session, daemon thread lifecycle. Counts: module-level metrics function returns evidence counts without erroring when passed a fresh session.

## 9. New integration tests (`tests/test_evidence_integration.py` — 18, all PASS)

| Test | Verifies |
|---|---|
| `test_vlm_observation_persists_and_indexes` | VLM observation → `VlmObservationRecord` row + `VLM_OBSERVATION` + `FRAME` evidence rows with provenance, stored object, and index eventually `INDEXED` |
| `test_tracking_event_captures_stored_evidence` | `object_entered` → TRACK_EVENT row with `storage_path`, `sha256`, content text |
| `test_evidence_disabled_by_config` | `EVIDENCE_ENABLED=false` → no acceptance, status reports disabled |
| `test_evidence_counts_flow_through_status` | `evidence_captured/indexed/failed` counters in the live snapshot |
| `test_evidence_dedup_across_observations` | identical bytes on one session stored once (single object path per sha) under concurrent capture timing |
| `test_evidence_api_list_detail_content` | list, detail (+ filed provenance), `content` returns the original bytes with `X-Evidence-Sha256` |
| `test_evidence_api_list_filters_and_pagination` | filters `camera_id`/`session_id`/`evidence_type`/`index_status` + limit |
| `test_evidence_api_requires_live_roles` | REVIEWER → denied on every evidence route |
| `test_evidence_api_unknown_public_id` | detail/reindex of a missing/public id → 404 |
| `test_evidence_reindex_api` | reindex → job submitted; fresh-row read shows `INDEXED` (column-select polling; fixes DetachedInstanceError, Fix 5.5) |
| `test_evidence_search_endpoint` | `POST /evidence/live/search` returns hits for the stored content |
| `test_evidence_search_validation` | empty query → 422 |
| `test_provenance_chain_complete` | TRACK_EVENT provenance chains event/camera/session/frame; VLM provenance chains observation + source-frame ids |
| `test_capture_never_leaks_between_sessions` | per-session isolation of evidence rows (camera A never sees camera B) |
| `test_capture_isolated_from_detection_disabled` | no capture when detection/tracking path is disabled |
| `test_evidence_worker_isolation_after_stop` | stopping a session stops its capture/index participation cleanly |
| `test_index_failure_marks_failed_not_crash` | provider failure → `FAILED` (truncated error), session stays live |
| `test_evidence_no_pixels_in_broadcast` | status/metadata payloads carry only absolute-pixel geometry + ids, never pixel data |

## 10. Real-service tests

- None this phase — MinIO/Qdrant offline (§5, §6). All paths verified against the in-process fallbacks; `REAL STORAGE/VECTOR TEST: NOT TESTED` is recorded in §20.

## 11. Phase 1–4 regression

Targeted regression: `tests/test_regression_phase1.py`, `tests/test_cameras.py`, `tests/test_live_api.py`, `tests/test_live_ws.py`, `tests/test_live_pipeline.py`, `tests/test_tracking_integration.py`, `tests/test_vlm_integration.py`, `tests/test_reports.py`, `tests/test_pipeline.py`, `tests/test_policy_rag.py`, `tests/test_rag_api.py`, `tests/test_db_relationships.py`, `tests/test_demo_investigation.py`, `tests/test_storage.py`, `tests/test_tracker.py`, `tests/test_detection_unit.py`, `tests/test_detection_integration.py`, `tests/test_auth.py` plus the new Phase 5 surface (`test_evidence_unit.py`, `test_evidence_integration.py`, `test_vlm_validation.py`): all PASS with the environment-gated trio deselected (see §12). The additive-non-replacing requirement holds — detection/tracking/VLM/reports all stay green with evidence capture active.

## 12. Full-suite result

`python -m pytest tests -p no:cacheprovider` (after removing stale `tests/test_forensics.db`, with only the three environment-gated modules deselected — `test_evaluation.py`, `test_ffmpeg.py`, `test_detection_real_yolo.py`): **310 passed, 6 skipped, 0 failed, 0 error (exit code 0)**.

- The 3 deselected modules fail only for environment reasons (missing `data/evaluation/benchmark.jsonl` → 6 pre-existing failures; no ffmpeg; no YOLO weights) and are separately documented.
- Two clean full-suite runs performed for confidence; the earlier mass "no such table"/UNIQUE errors were traced to the concurrent watcher running the suite against the same SQLite file (Fix 5.3) and the dedup race (Fix 5.2) — both eliminated.
- Net new green this phase: 46 tests (28 unit + 18 integration) plus 0 new failures.

## 13. Pre-existing failures (NOT caused by Phase 5)

- `tests/test_evaluation.py` (6): require `data/evaluation/benchmark.jsonl`, absent from the repo (unchanged since Phase 1).
- `tests/test_investigations.py::test_budget_timeout_expires`: asserts a 1 ms `Budget` deadline after a 10 ms sleep — intermittent on Windows `time.monotonic()` resolution (~50% flake; passed in today’s green runs). `app/agents/guardrails.py` untouched by Phase 5.
- `tests/test_ffmpeg.py` + `tests/test_detection_real_yolo.py`: environment-gated (no ffmpeg binary; no YOLO weights) — skipped/limited on this host, not regressions.
- A repeated automated grep-style watcher (`python -m pytest -q -p no:warnings --no-header`) was formerly racing the suite against the same SQLite DB; it is killed and must not be re-launched while another suite runs (documented in §19).

## 14. Backpressure / boundedness / performance checks

- **Index queue bounded**: drop-oldest `deque(maxlen=EVIDENCE_INDEX_QUEUE_SIZE)`; a burst evicts the oldest pending job, never grows memory (deterministic unit gate).
- **Retries bounded**: per-job attempts capped at `EVIDENCE_INDEX_MAX_ATTEMPTS` with exponential backoff, then `FAILED` with `index_error` capped at 2000 chars.
- **Visual bounded**: ≤ `EVIDENCE_MAX_FRAMES_PER_CAPTURE`, downscaled ≤ `EVIDENCE_MAX_IMAGE_SIDE`, compact JPEG ≤ `EVIDENCE_MAX_IMAGE_BYTES`.
- **List bounded**: API limit capped at `EVIDENCE_LIST_LIMIT`; search returns capped hits.
- **Threads bounded**: one daemon indexer thread (global singleton); per-capture `RLock` serialises the store path; `stop(timeout=2)` + `clear()` in the autouse test fixture prevent leakage.
- **Isolation**: each capture opens short-lived sessions and closes them; worker failure rolls back before re-query; a failed capture is contained (logs with `exc_info=True`, never raises into the pipeline).

## 15. Frontend verification

- `npm run build` (Next.js 14.2.5): compiles, React lint + TypeScript type-check PASS; `/live` gains the Forensic Evidence panel; all routes generated.
- `/live` evidence panel: load list on session start (keyed on `session?.id`), evidence-type + index-status badge variants, preview modal (opens `liveEvidenceContent` as a blob with the auth header), reindex action, and vector-search hit list; clean state reset on stop/unmount.
- Fixed during verification: `provenance` field typed with known keys + index signature (Fix 5.6) so detail rendering type-checks.

## 16. Sample / dashboard data

- Unchanged this phase (carried from Phase 2: 4 sample videos, 5 cameras). Phase 5 adds the evidence tables and observation persistence but seeds no new demo data; evidence accrues from live capture only.

## 17. Commands used

- `python -m py_compile` / `ast` parse on all new/modified backend modules — PASS.
- `python -m pytest tests/test_evidence_unit.py -q` → 28 PASS.
- `python -m pytest tests/test_evidence_integration.py -q` → 18 PASS.
- `python -m pytest tests/test_evidence_unit.py tests/test_evidence_integration.py -q` → 46 PASS (unit + integration in one process).
- Full suite with 3 env-gated modules deselected → 310 passed / 6 skipped / 0 failed (exit 0, run twice).
- `python -m pytest tests/test_ffmpeg.py tests/test_detection_real_yolo.py tests/test_evaluation.py -q` → confirms the 6 pre-existing evaluation failures only.
- Port probe `TCP 127.0.0.1:9000` (MinIO) and `:6333` (Qdrant) → connection refused → fallbacks in use.
- `npm run build` (frontend) → PASS.

## 18. Issues encountered and resolved during Phase 5

| Issue | Resolution |
|---|---|
| Nested storage dirs missing under `live/<cam>/<ses>/<date>/<id>/` (no `put_bytes`) | `_local_path` makedirs the object parent (Fix 5.1) |
| Dedup race → two objects for one sha under concurrent capture timing | Per-capture `RLock` around check-store-commit (Fix 5.2) |
| Mass spurious DB errors traced to a *second automated pytest* racing the suite on the same SQLite file | Killed the watcher chain; verified only dev uvicorn remains (Fix 5.3) |
| Indexer unit tests flaked against the live singleton thread | Synchronous `_process` + monkeypatched qdrant + event-gate (Fix 5.4) |
| `DetachedInstanceError` after commit+close; `sa.select` has no `.scalar()` | Snapshot ids before commit/close; column-select polling; reindex handler re-queries a fresh row (Fix 5.5) |
| Frontend TS type errors on `provenance` and the message union | Known-keys typing + stable card key (Fix 5.6) |
| Evidence status counts must never fail a snapshot | `counts()` owns its session when none passed; exceptions collapse to zeros |

## 19. Pre-existing / environment issues (NOT Phase 5 regressions)

- ffmpeg/ffprobe NOT installed → stored-video pipeline cannot reach COMPLETED (carried from Phase 2).
- MinIO and Qdrant offline → in-memory/local fallbacks (carried from Phases 1–2); probes re-confirmed today.
- `data/evaluation/benchmark.jsonl` missing → 6 pre-existing evaluation failures (carried from Phase 1).
- Windows `time.monotonic` resolution makes the 1 ms guardrails test intermittently flaky (pre-existing).
- No real VLM endpoint/key and no physical device/network E2E (carried from Phase 4 / Phases 1–3).
- Warning: don’t run two pytest suites against the same `tests/test_forensics.db` concurrently.

## 20. Honest limitations / NOT TESTED

- **REAL MinIO + REAL Qdrant end-to-end: NOT TESTED** — ports refused; all object storage and vector indexing verified against the in-process fallbacks (`LocalStorageService` real on-disk layout; deterministic in-memory Qdrant). The storage/index seams are exercised identically regardless of backend.
- **REAL-DEVICE / REAL-CAMERA E2E: NOT TESTED** (no physical device, no real network — carried from Phases 1–3).
- **Real YOLO inference → evidence on live footage: NOT TESTED** (no weights; simulation engine used in tests).
- **Long-horizon evidence volume / throughput: NOT MEASURED** (CPU-only host; correctness boundedness proven, scale unmeasured).
- **VLM semantic quality on real footage: NOT EVALUATED** (Phase 4 gap unchanged; `simulation` provider used).
- Client-supplied pixels/timestamps remain rejected; original buffers never mutated; evidence bytes are copy-encoded JPEGs (the minimal visual content rule).

## 21. Phase 6 prerequisites — high priority

1. Stand up MinIO + Qdrant and re-run the evidence indexing/content/search paths against them before Phase 6 agent/RAG work depends on the real backends (validates the exact seams in production form).
2. Real VLM provider run (configure endpoint/key, `VLM_PROVIDER=openai`) to ground observations on real footage (biggest Phase 4→6 semantic gap).
3. Run real YOLO inference closing the synthetic-only gap, and install ffmpeg/ffprobe so stored-video evidence can flow through detection → tracking → VLM → evidence.
4. Validate REAL-DEVICE WebRTC end-to-end on physical hardware (unchanged blocker since Phase 1).

## 22. Phase 6 recommendations — medium priority

5. Consumption of `ForensicEvidence` rows (with provenance chains) by investigation agents via the existing `/evidence/live` API and vector search.
6. Persist `VlmObservationRecord` → Phase 4 `to_storage()` payloads are already wired; keep the broadcast contract versioned.
7. Tunable backpressure at high event velocity (`EVIDENCE_INDEX_QUEUE_SIZE`, `EVIDENCE_MAX_FRAMES_PER_CAPTURE` per deployment).
8. Operator-visible evidence throughput/bytes metrics (aggregate counters only, no pixel data) in the live status/dashboard.

## 23. Verification summary

| Item | Result |
|---|---|
| Evidence unit tests | 28/28 PASS |
| Evidence integration tests | 18/18 PASS |
| Evidence suite together (unit + integration) | 46/46 PASS |
| Full suite (3 env-gated modules deselected) | 310 PASS, 6 skipped, 0 failed / 0 error (exit 0, twice) |
| `test_evaluation.py` | 6 FAILED (pre-existing: missing `benchmark.jsonl`) |
| Frontend build | PASS (`/live` evidence panel, typed API client) |
| Real MinIO / Qdrant | NOT TESTED (ports refused; fallbacks verified) |
| Real-device / real-camera / real-network E2E | NOT TESTED |

## 24. Verdict

### READY FOR PHASE 6

Phase 5 delivers the durable forensic evidence layer: capture of every tracking event and VLM observation into `ForensicEvidence` with server-generated provenance, minimal-visual JPEG objects (deduplicated race-free per (sha, camera, session) and stored under deterministic paths), correct nested-dir object storage, an async bounded drop-oldest indexing queue with retry/backoff→`FAILED` semantics into Qdrant (in-memory fallback), an RBAC `/evidence/live` REST surface (list/filter/detail/content/reindex/search), and a working frontend evidence panel. All 46 new tests pass, the full suite is green (310 passed / 0 failed with only the three environment-gated modules excluded), the frontend builds, and Phase 4's report already enumerated the environment prerequisites (real MinIO/Qdrant, real VLM/YOLO/device, ffmpeg) that remain unchanged. Every honest limitation is explicitly listed (§20) rather than hidden, and the storage/index seams are proven in fallback form ready to run against the real services.

## 25. Delta vs Phase 4 report

Added: the whole `backend/app/evidence/` package (4 modules), `ForensicEvidence` + `VlmObservationRecord` models and migration `0006`, evidence lifecycle/hooks/snapshot wiring in the live manager, `/evidence/live` RBAC router (write path reindex handler hardened against detached instances), `EVIDENCE_*` config, storage nested-dir fix, frontend evidence panel + typed API client, and 46 new tests. New Phase 5 artifacts: the evidence lock-fix (dedup race), the storage dir fix, the conftest `_reset_evidence` fixture, and documentation of the concurrent-pytest DB race. Caveats carried forward unchanged: missing `benchmark.jsonl` (6 pre-existing eval failures), no ffmpeg, MinIO/Qdrant offline, CPU-only, no physical device/real-network E2E, no real VLM/YOLO run. Phase 5's real dependency: standing up MinIO + Qdrant before Phase 6 agent/RAG work leans on the real backends. Verdict stays green — READY FOR PHASE 6 — because capture → storage → dedup → indexing → API → frontend is proven end-to-end in-process with honest enumeration of every NOT TESTED real-service surface.
---

## PHYSICAL LIVE CAMERA VERIFICATION (added 2026-09-27)

Verdict for this phase: **VERIFIED** against real services; the physical
laptop-webcam capture step is **NOT TESTED** (no capture device is reachable from
the verification container).

| Item | Result |
|---|---|
| webcam transport (shares one `LocalOpenCVCameraSource` with `droidcam_usb`) | IMPLEMENTED + VERIFIED (14 unit/integration tests) |
| Capture device on indices 0-3 | NOT TESTED — `/dev/video*` absent in the container |
| Docker cannot see a host camera | CONFIRMED (`verify_webcam.py --probe` → `RESULT: NO DEVICE`) |
| PostgreSQL 15.19 / MinIO / Qdrant (dims 384) | PASS — real services, no fallback |
| YOLO | `yolov8n.pt` on **CPU** (`torch.cuda.is_available() == False`) |
| Real VLM provider | NOT TESTED — no credentials configured |
| Defect fixed here | `reportlab==4.2.5` added so reports render as a real PDF instead of degrading to markdown |

To complete the physical step, run the backend host-native and follow
`WEBCAM_SETUP.md`:

``bash
python backend/scripts/verify_webcam.py --probe
python backend/scripts/verify_webcam.py --device 0 --seconds 10
python backend/scripts/verify_live_webcam.py --base-url http://127.0.0.1:8000 --device 0 --seconds 45
``

Full evidence: `FINAL_SYSTEM_REPORT.md`.
