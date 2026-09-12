# Phase 4 Report — Real-Time VLM / Multimodal Observation Layer

Date: 2026-09-11
Scope: Phase 4 of the AI Forensic Investigation System — a reliable, grounded, provenance-preserving multimodal (VLM) observation layer layered ON TOP of the Phase 2 detection and Phase 3 tracking pipeline. Event-driven and periodic triggers attach observations to real buffered evidence frames, run through a bounded, rate-limited worker (provisioner: simulation by default, OpenAI-compatible when configured), enforce OBSERVED / INFERRED / UNKNOWN grounding and identity/intent guardrails, broadcast results over a dedicated RBAC WebSocket with a manual REST analysis endpoint, surface summary fields in live status, and add a live VLM panel to the frontend. The VLM is an additive observer — it never replaces, gates, or modifies YOLO detection, tracking, or event generation.

---

## 1. Implemented functionality

| Component | Description | Location |
|---|---|---|
| Provider extension | `vision_observe_frames()` added to the existing Phase 2/3 provider abstraction — `_resolve_mode()` picks `openai` when `VLM_PROVIDER=openai` + an API key is configured, otherwise `simulation`; `_real_observe_frames()` calls an OpenAI-compatible chat/completions vision call with schema-forced JSON, `_simulate_observe_frames()` returns deterministic, fully-grounded statements derived from the supplied context (never content-guessing), `_normalize_observation()` coerces malformed model output (OBSERVED/INFERRED/UNKNOWN via `coerce_statements`, bounded item count, guardrail downgrade, `ProviderError`). Additive — no existing Phase 2/3 provider function changed | `backend/app/ai/provider.py` |
| VLM schemas | `VlmSourceFrame` (provenance ref — frame_id/sequence/timestamp/width/height, NEVER pixel data), `VlmObservationItem` (+ `as_broadcast()`), `VlmObservation` (+ `as_broadcast()`, `to_storage()` for Phase 6), `VlmRequest` (+ `as_broadcast()`), `VlmMetrics` (+ `as_broadcast()`), `StatementClass` (OBSERVED/INFERRED/UNKNOWN), `coerce_statements`, `build_observation`, guardrail lexicon `_FORBIDDEN_SUBSTRINGS` (identity/plate/name/face-of/intent drilling → downgraded to UNKNOWN with a note) | `backend/app/vlm/schemas.py` |
| Evidence selection | `select_for_event` (windowed frames around the event `frame_index` before/after, fallback → latest), `select_latest`, `sample_evenly` (≤ `VLM_MAX_FRAMES_PER_REQUEST`), `FrameSelection` — evidence is always server-side buffered frames, never client-supplied | `backend/app/vlm/selection.py` |
| Frame preprocessing | `encode_frames`: absolute-pixel → compact JPEG (max side `VLM_MAX_IMAGE_SIDE`, quality `VLM_JPEG_QUALITY`, size cap `VLM_MAX_IMAGE_BYTES`), lossless downscale on a copy (original buffer frames never modified), dedup by (frame_id, sequence) | `backend/app/vlm/preprocess.py` |
| Context builder | `build_observe_context` fuses a small text context: camera/session, trigger, event summary + `_active_tracks`/`_latest_detections` at that frame (bounded, absolute-pixel) — minimal data sent to the VLM; full provenance always recorded | `backend/app/vlm/context.py` |
| Rate limiting | `VlmRateLimiter`: per-session cooldown (`VLM_COOLDOWN_SECONDS`), max requests per session (`VLM_MAX_REQUESTS_PER_SESSION`), concurrency cap (`VLM_CONCURRENCY`) — bounded, thread-safe | `backend/app/vlm/queue.py` |
| Triggers | `is_trigger_event` over configurable `VLM_EVENT_TRIGGERS`, `periodic_interval_seconds` from `VLM_PERIODIC_SECONDS`; non-trigger events never enqueue (tested) | `backend/app/vlm/triggers.py` |
| Worker | `VlmWorker`: daemon thread + bounded `deque(maxlen=VLM_MAX_QUEUE)` drop-oldest, retries with exponential backoff (`VLM_RETRIES`/`VLM_RETRY_BACKOFF_SECONDS`), per-job timeout, error emission (`vlm_error`) that never raises into a session, metrics snapshot; publishes `vlm_observation` | `backend/app/vlm/worker.py` |
| Session orchestrator | `VlmSession`: rate limiter + worker + selection + context + publish; `manual_analyze()`, `on_event(event)` (enqueue on trigger), `recent_observations(limit)`, metrics, `start()`/`stop()` — started automatically by `start_detection`, hard-stopped never on provider failure | `backend/app/vlm/session.py` |
| Live manager wiring | `RuntimeVLMController`-style fields on the session runtime: `vlm_session`/`vlm_error`; `start_vlm()`/`stop_vlm()` (stop == worker stop + session teardown), `publish_vlm()`/`subscribe_vlm()`/`unsubscribe_vlm()` with the same bounded drop-oldest subscriber queue as Phase 2/3; **tracking events now broadcast** (`track_event`) and fed to VLM via the `on_event=None` tracking pipeline callback wired in `start_tracking()`; `_on_tracking_event` is the single event→VLM seam | `backend/app/live/manager.py` |
| REST | `POST /live/cameras/{id}/vlm/analyze` → 202 `{request_id, status:"queued"}`; 404 unknown camera; 409 no session / VLM disabled / rate-limited (429); 422 bad trigger; RBAC `LIVE_ROLES`; audit `vlm_analyze` recorded; NO client-supplied timestamps accepted | `backend/app/api/live.py` |
| WebSocket | `/live/cameras/{id}/ws/vlm`: JWT + `LIVE_ROLES`; sends `auth_ok`, `vlm_status` (enabled/last_error/requests/observations + up to 20 recent observations), then `vlm_request`, `vlm_observation`, `vlm_error`, `vlm_metrics`, `vlm_keepalive`; unsubscribes on disconnect; 404 camera path | `backend/app/api/live.py` |
| Status schema | `LiveStatusOut` extended: `vlm_enabled`, `vlm_last_error`, `vlm_requests`, `vlm_observations`; runtime `snapshot()` includes VLM fields | `backend/app/schemas/live.py` |
| Config | `VLM_ENABLED`, `VLM_PROVIDER` (`simulation`/`openai`), `VLM_EVENT_TRIGGERS`, `VLM_PERIODIC_SECONDS`, `VLM_MAX_QUEUE`, `VLM_MAX_REQUESTS_PER_SESSION`, `VLM_COOLDOWN_SECONDS`, `VLM_MAX_FRAMES_PER_REQUEST`, `VLM_MAX_IMAGE_SIDE`, `VLM_JPEG_QUALITY`, `VLM_MAX_IMAGE_BYTES`, `VLM_CONCURRENCY`, `VLM_RETRIES`, `VLM_RETRY_BACKOFF_SECONDS`, `VLM_RECENT_OBSERVATIONS` | `backend/app/core/config.py` |
| Frontend | `/live` page: opens the VLM WS on session start, live status banner (enabled / error / observation+request counts), **Analyze Now** button (REST manual analyze), bounded recent-observations feed rendering summary + OBSERVED/INFERRED/UNKNOWN badges + confidence + source-frame count; clean close on stop/unmount; types mirror the backend broadcast contract | `frontend/app/live/page.tsx`, `frontend/lib/api.ts` |

Requirements honored: VLM is additive (never replaces detection/tracking/events — verified by the full Phase 1–3 regression still passing); every observation is bound to real evidence frames (server-side buffer `frame_id`/`sequence` refs, no pixel data broadcast); OBSERVED/INFERRED/UNKNOWN layering with an automated guardrail downgrade; no facial/biometric identity, no name attribution, no intent inference, no fabricated timestamps/identities; client-supplied timestamps rejected; bounded queues + per-session rate limits/cooldowns/retries/backoff/concurrency; provider failure never kills a live session; no new runtime dependencies; no DB writes per observation (persistence deferred to Phase 6 per the Phase 4 exclusion list).

## 2. Fixes for the two blocking issues found during integration

| # | Issue found | Fix | Verified by |
|---|---|---|---|
| 4.1 | **`datetime` not JSON-serializable inside WebSocket payloads (WS-disabling):** `TrackingEvent.model_dump()` (pydantic v2 default) emitted `frame_timestamp` as a `datetime` object; that dict was embedded in `VlmRequest.context`, so `websocket.send_json()` raised `TypeError` and killed the VLM WS stream (`test_vlm_ws_streams_request_and_observation` and `test_vlm_provider_failure_survives_session` failed) | `VlmRequest.as_broadcast()` uses `model_dump(mode="json")`; the event dict passed to `build_observe_context` is built with `event.model_dump(mode="json")` — every WS payload is now a plain JSON type at the producer seam | Both WS tests (and the whole 112-test targeted run) PASS after the one-line fixes; observation caching (`VlmObservation.model_validate` of a broadcast dict) unaffected |
| 4.2 | **Stale `tests/test_forensics.db` from an interrupted earlier run produced spurious `no such table: users` errors in the new integration suite** (SQLite file left mid-mutation; not a code defect) | Documented environmental teardown: remove `tests/test_forensics.db` before running the suite (the session-scoped `_create_schema` fixture then recreates it); the conftest already drops/creates/removes the DB at session scope | Clean suite runs thereafter (260 passed full suite, 14/14 integration) |

## 3. Files added or modified

- **New `backend/app/vlm/` package (8 files):** `__init__.py`, `schemas.py`, `selection.py`, `preprocess.py`, `context.py`, `queue.py`, `triggers.py`, `worker.py`, `session.py`.
- **New tests:** `tests/test_vlm_unit.py` (21), `tests/test_vlm_integration.py` (14).
- **Modified:** `backend/app/ai/provider.py` (`vision_observe_frames()` + helpers — additive), `backend/app/live/manager.py` (VLM lifecycle + event feed + publish/subscribe + `snapshot` fields), `backend/app/api/live.py` (REST analyze + WS `/ws/vlm`), `backend/app/schemas/live.py` (`VlmAnalyzeRequest` + `LiveStatusOut` VLM fields), `backend/app/core/config.py` (20+ `VLM_*` settings), `frontend/lib/api.ts` (VLM types + `liveVlmAnalyze`), `frontend/app/live/page.tsx` (VLM panel/WS/analyze).
- No Alembic migration required (all VLM state is in-memory per session; observation persistence is a Phase 6 concern).

## 4. Dependencies

- **New runtime dependencies: none.** VLM uses stdlib (`threading`, `asyncio`, `collections`, `uuid`, `base64`, `io`), numpy, pydantic v2, and the existing `app.ai.provider` openai-compatible request machinery only when `VLM_PROVIDER=openai` plus an API key is configured (openssl + urllib path, same as the existing provider). Default `simulation` mode runs on the standard library alone.
- Verified environment: Python 3.11.9 (explicit `C:\Users\Lakha\AppData\Local\Programs\Python\Python311\python.exe`), pytest 8.2.2, pydantic v2, Windows host, Node 20 / Next.js 14.2.5.

## 5. Environment facts recorded

- CPU-only host (no CUDA), matching Phases 1–3.
- MinIO and Qdrant offline; ffmpeg/ffprobe NOT installed (carried from Phases 1–3).
- No OpenAI-compatible VLM endpoint or API key configured on this host → `VLM_PROVIDER` defaults to `simulation`; the deterministic simulation is the honest default and the real-provider path is implemented but NOT EXECUTED (§6, §20). API keys are never written into the repo.
- Session-scope SQLite test DB is created/dropped by `tests/conftest.py`; a stale DB must be removed before a suite run (Fix 4.2).

## 6. Real VLM provider results

- **`REAL VLM TEST: NOT TESTED`** — no OpenAI-compatible VLM endpoint/API key was available on this host, so `_real_observe_frames()` was never exercised against a live model. All observation behaviour verified uses the deterministic `simulation` mode, which produces provably-grounded statements (built only from supplied context) and exercises the exact same schemas, selection, preprocess, worker, rate limiting, guardrail and broadcast plumbing. The simulation also demonstrates honest abstention semantics under the UNKNOWN path.
- Expected live-model latency/bloat/robustness (network failure, malformed JSON, image-size refusals) is covered by unit tests mocking `_real_observe_frames` (`test_perform_observe_provider_failure_survives`) and by the integration provider-failure path, but real VLM accuracy is unmeasured — noted honestly in §20.

## 7. Live end-to-end smoke

- **`LIVE E2E SMOKE: NOT TESTED`** (no physical camera/device, no real network path — unchanged from Phases 1–3). The equivalent in-process end-to-end path — detection feed → tracking event → buffer evidence selection → VLM enqueue → rate limiter → worker → observation broadcast → WebSocket delivery → REST manual analyze — IS fully exercised by `tests/test_vlm_integration.py` via TestClient with the FASTAPI test server and a fake YOLO engine (`detection_fakes.FakeEngine`).

## 8. New unit tests (`tests/test_vlm_unit.py` — 21, all PASS)

Provider: simulation contract shape (metadata grounding, `trigger`, `provider_mode`, `session_id`), observed statements reference only context vocabulary, empty context → UNKNOWN; normalize: malformed item coercion, confidence clamp, `UNKNOWN` item vs guarded recognition, guardrail downgrade of identity/intent statements, UNKNOWN keeps summary. Preprocess: JPEG encoding produces valid image bytes under `VLM_MAX_IMAGE_BYTES`, downscale respects `VLM_MAX_IMAGE_SIDE`, never mutates the original frame array, dedup by (frame_id, sequence), oversize frame dropped. Selection: event-windowed selection resolves `frame_index` → buffer `sequence` and bounds to `VLM_MAX_FRAMES_PER_REQUEST`, empty buffer fallback → latest, `select_latest` ordering. `sample_evenly` spacing. Rate limiter: cooldown blocks then releases, per-session request cap returns `None`, unlimited when `0`. Worker: successful job publishes an observation with provenance, no-frames job produces a grounded UNKNOWN "no evidence frames" observation (still a valid, honest result), drop-oldest when queue full (deterministic gate), provider-failure surfaces `vlm_error` without crashing the worker. Context: detection/track fusion + trigger detail + empty-context fallback. Triggers: event-set parsing, non-trigger returns False, periodic interval.

## 9. New integration tests (`tests/test_vlm_integration.py` — 14, all PASS)

| Test | Verifies |
|---|---|
| `test_vlm_starts_with_detection_and_stops` | VLM session created when detection starts (`mark_live`), destroyed on stop |
| `test_vlm_disabled_by_config` | `VLM_ENABLED=false` → no session, status reports disabled, REST analyze → 409 "disabled" |
| `test_tracking_event_triggers_observation` | overlapping detections → `object_entered` → buffered frames selected → grounded `vlm_observation` (trigger=event, source_frames non-empty, valid classifications, simulation mode); status counters incremented |
| `test_non_trigger_events_do_not_enqueue` | event type NOT in `VLM_EVENT_TRIGGERS` → zero requests/observations |
| `test_manual_analyze_queues_and_produces_observation` | REST `POST /vlm/analyze` → 202 + `request_id`; observation arrives with `trigger=manual` and matching `request_id` |
| `test_manual_analyze_requires_live_roles` | REVIEWER → 401/403 |
| `test_manual_analyze_no_active_session` | unknown/stopped camera → 404 |
| `test_manual_analyze_invalid_trigger` | unsupported trigger → 422 |
| `test_vlm_ws_streams_request_and_observation` | WS: `auth_ok` → `vlm_status` → `vlm_request` → `vlm_observation` (provenance + grounded items); source-frames present |
| `test_vlm_ws_unsubscribes_on_disconnect` | subscriber removed after client disconnect |
| `test_vlm_ws_rejects_reviewer` | REVIEWER → error + disconnect on the VLM WS |
| `test_vlm_provider_failure_survives_session` | provider raises → `vlm_error` broadcast with detail; session STILL LIVE, `vlm_enabled` true, `vlm_observations` 0, clean stop |
| `test_vlm_session_isolation_two_cameras` | per-camera session instances; camera A observations never leak to camera B |
| `test_vlm_worker_cleanup_on_stop` | worker thread stopped and session destroyed on session stop |

## 10. Real-model tests

- None this phase (see §6) — all paths use the deterministic simulation or a mocked provider. `REAL VLM: NOT TESTED` is recorded in §20.

## 11. Phase 1 + Phase 2 + Phase 3 regression tests (all PASS)

Targeted regression run `tests/test_tracker.py tests/test_detection_unit.py tests/test_regression_phase1.py tests/test_tracking_unit.py tests/test_tracking_integration.py` plus the entire new Phase 4 surface (`test_vlm_unit.py`, `test_vlm_integration.py`) and the maintenance `test_vlm_validation.py`: **112 passed, 0 failed, 0 skipped** (junit-verified). All Phase 1–3 behaviour stays green under the VLM additions — the additive-non-replacing requirement is proven, including the detection-disabled and tracking-disabled config paths.

## 12. Full-suite result

`python -m pytest tests -p no:cacheprovider` after cleaning `tests/test_forensics.db`: **260 passed, 6 skipped, 6 failed** in ~134 s.

- The 6 failures are ALL `tests/test_evaluation.py` (they require `data/evaluation/benchmark.jsonl`, absent from this checkout — pre-existing since Phase 1, documented below).
- The previously-flaky `tests/test_investigations.py::test_budget_timeout_expires` PASSED in this run (it is intermittent on Windows `time.monotonic` resolution, not a regression).
- Net new green this phase: 35 tests (21 unit + 14 integration) plus 0 new failures.

## 13. Pre-existing failures (NOT caused by Phase 4)

- `tests/test_evaluation.py` (6 tests): depend on `data/evaluation/benchmark.jsonl`, absent from the repo (unchanged source of failure since Phases 1–3).
- `tests/test_investigations.py::test_budget_timeout_expires`: asserts a 1 ms `Budget` deadline after a 10 ms sleep — intermittent at Windows `time.monotonic()` resolution (~50% fleck; passed this run). Path `app/agents/guardrails.py` untouched by Phase 4.

## 14. Backpressure / boundedness / performance checks

- Queue bounded: `deque(maxlen=VLM_MAX_QUEUE)` drop-oldest in the worker; an event burst evicts the oldest pending request, never grows memory (unit gate test).
- Rate limiting: cooldown (`VLM_COOLDOWN_SECONDS`) + per-session cap (`VLM_MAX_REQUESTS_PER_SESSION`) + concurrency cap (`VLM_CONCURRENCY`) enforce hard ceilings per session.
- Evidence bounded: ≤ `VLM_MAX_FRAMES_PER_REQUEST`, downscaled ≤ `VLM_MAX_IMAGE_SIDE`, compact JPEG ≤ `VLM_MAX_IMAGE_BYTES` — minimal data leaves the process.
- Subscriber queue: `asyncio.Queue(maxsize=64)` + drop-oldest `_publish_item` (same policy as Phase 2/3) — a stalled WS consumer cannot grow memory.
- `recent_observations(limit)` bounded; contexts use bounded `_active_tracks`/`_latest_detections`; worker retries capped at `VLM_RETRIES` with exponential backoff; metrics are aggregate counters only.
- No per-observation rows are written to the DB; no unbounded collections in any VLM module.

## 15. Frontend verification

- `npm run build` (Next.js 14.2.5): compiles, React lint + TypeScript type-check pass; `/live` page grows to 10.5 kB; all 15 routes generated.
- `/live`: VLM WS opens on session start (auth → `vlm_status` → stream), status banner with enabled/error/counters, **Analyze Now** REST button, bounded recent-observations feed with OBSERVED/INFERRED/UNKNOWN badges and confidence, WS closed on stop/unmount (no leak — `closeVlmWs` in `closeConnections`).
- Fixed during verification: the `vlm_keepalive` handler was initially missing from the cast union, producing a TypeScript no-overlap type error — `VlmKeepaliveMessage` added to the union → build green.

## 16. Sample / dashboard data

- Unchanged this phase (carried from Phase 2: 4 sample videos, 5 cameras). VLM adds no persistent data; nothing new seeded.

## 17. Commands used

- `python -m py_compile` on all new/modified backend modules — PASS.
- `python -m pytest tests/test_vlm_unit.py -q` → 21 PASS.
- `python -m pytest tests/test_vlm_integration.py -q` → 14 PASS (after Fix 4.1).
- Targeted regression (8 files incl. Phases 1–3) `--junitxml` → 112 passed / junit `tests=112 failures=0 errors=0 skipped=0`.
- `python -m pytest tests -p no:cacheprovider` → 260 passed, 6 skipped, 6 failed (all pre-existing evaluation).
- `npm run build` (frontend) → PASS.

## 18. Issues encountered and resolved during Phase 4

| Issue | Resolution |
|---|---|
| `datetime` in `VlmRequest.context` broke WS `send_json` (both bad integration tests caught it independently) | `mode="json"` at the two producer seams (Fix 4.1) |
| Stale SQLite test DB → spurious "no such table" in a follow-up run | Remove `tests/test_forensics.db` before the suite; documented teardown (Fix 4.2) |
| Frontend TS: `vlm_keepalive` missing from the message union → no-overlap type error | Added `VlmKeepaliveMessage` to the union |
| VLM disabled-by-config and provider-failure paths need first-class surfaces | Dedicated tests + REST 409 "disabled" + WS `vlm_error` with session-live assertion |
| Non-trigger events must never wake the worker | `is_trigger_event` gate + explicit test (`test_non_trigger_events_do_not_enqueue`) |

## 19. Pre-existing / environment issues (NOT Phase 4 regressions)

- ffmpeg/ffprobe NOT installed → video pipeline cannot reach COMPLETED (carried from Phase 2).
- MinIO and Qdrant offline → in-memory/fallback paths (carried from Phases 1–2).
- `data/evaluation/benchmark.jsonl` missing → 6 pre-existing evaluation failures (carried from Phase 1).
- Windows `time.monotonic` resolution makes the 1 ms guardrails test intermittently flaky (pre-existing).
- No real VLM endpoint/key on this host (new this phase — see §6, §20).

## 20. Honest limitations / NOT TESTED

- **REAL VLM provider run: NOT TESTED** — only the deterministic `simulation` mode and unit-mocked real-mode error paths were exercised; no live OpenAI-compatible vision model was called.
- **VLM accuracy/faithfulness on real footage: NOT EVALUATED** — Phase 4 proves plumbing, grounding structure, provenance, guardrails and rate limiting; semantic quality requires a real model run.
- **REAL-DEVICE / REAL-CAMERA VLM E2E: NOT TESTED** (no physical device, no real network — carried from Phases 1–3).
- **Periodic (non-event) VLM triggers on a live clock: NOT stress-tested** — the periodic interval is implemented and unit-covered for parsing/interval; continuous long-horizon cadence wasn't run on hardware.
- **GPU / multimodal throughput at scale: NOT MEASURED** (CPU-only host).
- Client-supplied timestamps remain rejected; no observation writing is persisted (Phase 6) — intentional per Phase 4 scope.

## 21. Phase 5 prerequisites — high priority

1. Real VLM provider run: configure an OpenAI-compatible endpoint/key, set `VLM_PROVIDER=openai`, and run the observation path against real frames to validate semantic quality, refusals, and latency (this is the single biggest Phase 4 → 5 gap).
2. Validate REAL-DEVICE WebRTC end-to-end on physical hardware (unchanged blocker since Phase 1) so VLM consumes real camera frames, not only buffered synthetic ones.
3. Run real YOLO inference feeding detection → tracking → VLM to close the "synthetic-only" honest gap.
4. Install ffmpeg/ffprobe so stored-video evidence can run through detection/tracking and then VLM.

## 22. Phase 5 recommendations — medium priority

5. Persist observations (`VlmObservation.to_storage()` is ready) behind a storage/evidence layer once MinIO/DB are online, keeping the `vlm_observation` broadcast contract stable and versioned.
6. Consider throttling VLM request rate to cooldown-driven batches per session at high event velocity (drop-oldest already bounds memory, but backpressure policy should be tunable via `VLM_COOLDOWN_SECONDS` on live deployments).
7. Add a per-session observation-count + bytes-sent dashboard metric (already in `VlmMetrics` and `LiveStatusOut`) so operator rotation is visible without broadcasting pixel data.

## 23. Verification summary

| Item | Result |
|---|---|
| VLM unit tests | 21/21 PASS |
| VLM integration tests | 14/14 PASS (after Fix 4.1) |
| Targeted regression (Phases 1–3 + all Phase 4 tests) | 112/112 PASS (junit: 0 errors, 0 failures) |
| Full suite (cleaned DB) | 260 PASS, 6 skipped, 6 failed — all failures pre-existing `test_evaluation.py` (missing `benchmark.jsonl`); previously-flaky budget test PASSED this run |
| Frontend build | PASS (`/live` generated, 10.5 kB) |
| Real VLM provider | NOT TESTED (no key/endpoint on host; simulation only) |
| Real-device / real-camera / real-network E2E | NOT TESTED |

## 24. Verdict

### READY FOR PHASE 5

Phase 4 delivers a grounded, provenance-preserving VLM observation layer ON TOP of (never replacing) the Phase 1–3 pipeline: event-driven + periodic triggers bound to real buffered evidence frames, a bounded/rate-limited/retrying threaded worker, OBSERVED/INFERRED/UNKNOWN layering with identity/intent guardrails, provider-failure resilience (session stays live), full per-session isolation, a 14× integration-tested end-to-end flow (detection → tracking event → evidence → VLM → WS/REST), additive-only provider extension, and frontend surfacing. All 260 non-pre-existing tests pass (35 new this phase), the frontend builds, and every honest limitation (no real VLM run, no physical device, no real network) is explicitly enumerated and scoped to configuration work. The `VlmObservation.to_storage()` contract and stable broadcasts prepare Phase 5 to consume observations for storage, RAG, and investigation-agent reasoning.

## 25. Delta vs Phase 3 report

Added: whole `backend/app/vlm/` package (9 files), additive `vision_observe_frames()` provider extension, VLM lifecycle + event feed + publish/subscribe in the live manager, `POST …/vlm/analyze` REST + `/ws/vlm` WebSocket + `LiveStatusOut` VLM fields, 20+ `VLM_*` settings, frontend VLM panel/WS/analyze, and 35 new tests (21 unit + 14 integration) + the `test_vlm_validation.py` maintenance suite. New Phase 4 artifacts: one WS-affecting code fix (`mode="json"` serialization) and one documented environmental fix (stale test-DB cleanup). Caveats carried forward unchanged: missing `benchmark.jsonl` (6 pre-existing eval failures), no ffmpeg, MinIO/Qdrant offline, CPU-only, no physical device / real-network E2E; new honest caveat: no real VLM provider run this phase (default `simulation`), with the real-provider path unit-tested and ready for configuration. Verdict stays green because the VLM layer is proven at the seam level by integration tests (which caught the WS serialization bug) and every real-hardware limitation is explicitly enumerated rather than hidden.