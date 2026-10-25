# Phase 3 Report — Real-Time Multi-Object Tracking Layer

Date: 2026-09-11
Scope: Phase 3 of the AI Forensic Investigation System — a modular, per-session, per-camera multi-object tracking layer consuming the Phase 2 `DetectionObject`/`DetectionFrame` contract from the live ingestion pipeline, assigning persistent visual track IDs, computing absolute-pixel motion metrics, detecting presence/social events, exposing tracks + metrics over a dedicated WebSocket with RBAC, and surfacing tracking state in live status and the frontend.

---

## 1. Implemented functionality

| Component | Description | Location |
|---|---|---|
| Tracking schemas | Stable Pydantic contracts: `TrackState` (NEW/ACTIVE/LOST/REMOVED), `TrackUpdate` (+ compact `as_broadcast()`), `TrackingEvent`, `TrackingMetricsOut`, `TrackSummary`, `utcnow()`; ALL units are ABSOLUTE FRAME PIXELS; visual IDs only — no facial/biometric identification | `backend/app/tracking/schemas.py` |
| Motion math | `center_of_bbox`, `displacement_px`, `path_distance_px`, `pixel_velocity_px_per_frame`, `stationary_seconds`, `moving_seconds`, `stationary_ratio`; constants `CENTER_MAX_PX=8`, `STATIONARY_TOLERANCE_PX=4`, `MOVING_TOLERANCE_PX=8`, `STATIONARY_MIN_SECONDS=20`, `STATIONARY_MIN_FRAMES=100` | `backend/app/tracking/motion.py` |
| IoU tracker | `IoUMultiObjectTracker`: greedy label-aware IoU matching (absolute-px bboxes, strongest-confidence first, LOST tracks preferred), persistent `Person-000001`-style visual IDs, bounded histories, `max_missing`/`max_tracks` bounds, thread-safe, `NEW→ACTIVE` at 3 hits, LOST/REMOVED transitions | `backend/app/tracking/tracker.py` |
| Event detector | `TrackEventDetector` over `EventThresholds` producing `TrackingEvent`s; bounded per-track state, `.reset()`/`.event_counts()`/`.total_events()` | `backend/app/tracking/event_detector.py` |
| Tracking metrics | Aggregate, thread-safe counters (active/lost/removed totals, updates, events-by-type, EMA latency) — IDs/bboxes/centers/frames are never stored or broadcast | `backend/app/tracking/metrics.py` |
| Tracking pipeline | `TrackingPipeline(session_id, camera_id, ...)` binds tracker + event detector + metrics; `.update(detections, frame_index, ts)`; `.snapshot()` → broadcast dict with LIVE `active_tracks` (derived from the tracker) | `backend/app/tracking/pipeline.py` |
| Lifecycle integration | `LiveSessionRuntime.start_tracking()`/`stop_tracking()`; tracking starts when detection starts (`mark_live()`), stops on terminal states and on `stop()`/`clear()` | `backend/app/live/manager.py` |
| Detection→tracking seam | `_normalize_detections` adapts `DetectionObject`/`BoundingBox` (and dicts) to the tracker's dict form; `_feed_tracking` publishes per-track `track_update` + `tracking_metrics` snapshots | `backend/app/live/manager.py` |
| Tracking WS | `/live/cameras/{id}/ws/tracking` — JWT auth + `LIVE_ROLES` (`ADMIN`/`SECURITY_OFFICER`/`INVESTIGATOR`); sends `tracking_status`, `track_update`, `tracking_metrics`, `tracking_keepalive`; unsubscribes on disconnect; 404 on missing camera | `backend/app/api/live.py` |
| Status schema | `LiveStatusOut` extended: `tracking_enabled`, `active_tracks`, `total_events`; status REST now includes the tracking snapshot | `backend/app/schemas/live.py` |
| Config | `TRACKING_ENABLED`, `TRACKING_IOU_THRESHOLD` (0.3), `TRACKING_MAX_MISSING` (30), `TRACKING_MAX_TRACKS` (200) | `backend/app/core/config.py` |
| Frontend | `/live` page opens the tracking WS alongside detection, renders a tracking-active banner + live metrics (active tracks/events/updates) + recent tracking-events feed; type definitions match the backend broadcast contract | `frontend/app/live/page.tsx`, `frontend/lib/api.ts` |

Requirements honored: per-session/per-camera tracker isolation (no cross-camera or cross-session leaks); bounded queues/history (`max_tracks`, bounded center/bbox histories, subscriber queue with drop-oldest); never blocks the FastAPI event loop (same `call_soon_threadsafe` subscriber pattern as Phase 2); no facial recognition, no name attribution, no real-world meter mapping; absolute-pixel units only; no DB writes per track/update; no new dependencies (numpy + existing vision IoU convention); metrics broadcast keeps aggregate counters only.

## 2. Fixes for the two blocking issues found during integration

| # | Issue found | Fix | Verified by |
|---|---|---|---|
| 3.1 | **Detection→tracking contract mismatch (production-disabling):** `manager._feed_tracking` passed pydantic `DetectionObject`s to the tracker, which calls `det.get("confidence")` / `det["bbox"]` (dict-only). Live tracking would raise every frame and be silently swallowed by the catch-all ("Tracking feed error") | Adapter `_normalize_detections` (static) converts `DetectionObject` (`class_name`/`BoundingBox`) and plain dicts into the tracker's dict form (`label`/`confidence`/`bbox`) once at the integration seam — neither layer changes | `test_normalize_detections_converts_objects_and_dicts`, `test_feed_tracking_produces_tracks_and_metrics` |
| 3.2 | **`active_tracks` reported a cumulative counter, not a live count** (status/WS showed 3 for one track after 3 updates) | `TrackingPipeline.snapshot()` derives `active_tracks` from the tracker's current `NEW`/`ACTIVE` tracks; the cumulative counter is preserved as `active_updates` (ID-free metrics unchanged) | `test_tracking_metrics_flow_through_status`, `test_tracking_ws_streams_updates`, `TestPipeline.test_stop_releases` |

## 3. Files added or modified

- **New:** `backend/app/tracking/` (`__init__.py`, `schemas.py`, `motion.py`, `tracker.py`, `event_detector.py`, `metrics.py`, `pipeline.py`); `tests/test_tracking_unit.py` (12), `tests/test_tracking_integration.py` (10).
- **Modified:** `backend/app/live/manager.py` (tracking lifecycle + seam + snapshot), `backend/app/api/live.py` (tracking WS), `backend/app/schemas/live.py` (tracking fields), `backend/app/core/config.py` (TRACKING_* settings), `backend/app/tracking/schemas.py`/`metrics.py`/`pipeline.py` (3.2 semantics), `frontend/app/live/page.tsx`, `frontend/lib/api.ts`.
- No Alembic migration required (all tracking state is in-memory; aggregate metrics only).

## 4. Dependencies

- **New dependencies: none.** Tracking uses stdlib (`threading`, `math`, `datetime`), numpy, and the existing `app.vision.tracker` IoU convention.
- Verified environment: Python 3.11.9, pytest 8.2.2, pydantic v2 (Extra=ignore default exercised by the existing `peak_concurrent_tracks` passthrough), Windows host.

## 5. Environment facts recorded

- CPU-only host (no CUDA) — matches Phases 1–2.
- Tracking is pure float/int math on already-detected boxes: per-track cost is negligible next to upstream YOLO inference (Phase 2 measured ~138 ms/frame synthetic / ~615 ms/frame noise at 640×480).
- No Windows timer mocking was introduced; the flaky 1 ms guardrails test (see §13) is a test-design issue, not a code fix target for Phase 3.

## 6. Real YOLO / real-model results

- **Not executed this phase.** The tracking layer was exercised exclusively with synthetic `DetectionFrame`s and the fake YOLO engine. A real `yolov8n.pt` run feeding the tracking pipeline is listed as a Phase 4 prerequisite (§16-2). No accuracy/timings can be honestly reported for real footage.

## 7. Live end-to-end smoke

- **Not executed this phase.** Unlike Phases 1–2 (which ran smokes against the live backend with the real model), Phase 3 verification was done via unit + API/WS integration tests (TestClient) feeding synthetic detections. The full live-feed→YOLO→tracking path on a running backend is part of the NOT TESTED list (§20).

## 8. New unit tests (`tests/test_tracking_unit.py` — 12, all PASS)

Schemas/`utcnow`; motion helpers (center, displacement, absolute-px constants, cumulative path distance, stationary/moving seconds under a fake 5 FPS); tracker lifecycle (NEW creation + persistent ID, IoU match persists ID + hits→ACTIVE, LOST→REMOVED after `max_missing`); event detector returns typed events; metrics snapshot fields + broadcast shape; pipeline update+snapshot includes `active_tracks`; pipeline stop releases state (`active_tracks == 0`).

## 9. New integration tests (`tests/test_tracking_integration.py` — 10, all PASS)

| Test | Verifies |
|---|---|
| `test_tracking_starts_with_detection_and_stops` | Tracking pipeline created on `mark_live()` when detection starts; destroyed on stop |
| `test_tracking_metrics_flow_through_status` | 3 overlapping person frames → 1 live track; `tracking_enabled`/`active_tracks`/`total_events` in status REST |
| `test_tracking_disabled_by_config` | `TRACKING_ENABLED=false` → no pipeline; status reports disabled, 0 tracks |
| `test_session_isolation_two_cameras` | Distinct pipelines per session/camera; camera A tracks never leak to camera B |
| `test_normalize_detections_converts_objects_and_dicts` | Seam converts `DetectionObject`+`BoundingBox` and dicts to tracker form |
| `test_feed_tracking_produces_tracks_and_metrics` | `_on_detection_result` → `total_updates` grows, 1 live track, broadcast type/session/camera correct |
| `test_tracking_ws_streams_updates` | WS: auth_ok → tracking_status → `track_update` (Person-* id, absolute 4-int bbox, valid state) + `tracking_metrics` |
| `test_tracking_ws_rejects_reviewer` | REVIEWER → error + disconnect on the tracking WS |
| `test_tracking_ws_unsubscribes_on_disconnect` | Subscriber removed on client disconnect |
| `test_tracking_ws_on_missing_camera` | Unknown camera → error message + disconnect |

## 10. Real-model tests

- None this phase (see §6). Fake-engine-driven paths only.

## 11. Phase 1 + Phase 2 regression tests (all PASS)

`tests/test_tracker.py` (4), `tests/test_detection_unit.py` (20), `tests/test_regression_phase1.py` (8), plus the Phase 1 live/WS/API suites — unchanged behavior stays green under the tracking additions (44-test targeted run plus the full run in §12).

## 12. Full-suite result

`python -m pytest tests --ignore=tests/test_evaluation.py --deselect tests/test_investigations.py::test_budget_timeout_expires`: **193 passed, 6 skipped, 0 failed** in ~168 s. Deselect rationale in §13 — both exclusions are pre-existing and unrelated to Phase 3.

## 13. Pre-existing failures (NOT caused by Phase 3)

- `tests/test_evaluation.py`: depends on `data/evaluation/benchmark.jsonl`, absent from the repo (unchanged since Phase 1/2).
- `tests/test_investigations.py::test_budget_timeout_expires`: asserts a 1 ms `Budget` deadline (`timeout_seconds=0.001`) after a 10 ms sleep — at Windows `time.monotonic()` resolution this fails intermittently (~50% standalone; passes standalone other times). Code path `app/agents/guardrails.py` is untouched by Phase 3; pre-existing flake, not a regression.

## 14. Backpressure / boundedness / performance checks

- Tracker: `max_tracks` enforced; bounded center/bbox/confidence histories (60-entry window); LOST→REMOVED bounded by `max_missing`.
- Subscriber queues: `asyncio.Queue(maxsize=64)` + drop-oldest `_publish_item` (same policy as Phase 2) — a stalled WS consumer cannot grow memory; bursts coalesce to the newest item.
- Metrics: pure aggregate counters; `events_by_type` bounded by the small event vocabulary.
- No per-frame/per-track rows written to the DB; no unbounded collections in any tracking module.

## 15. Frontend verification

- `npm run build` (Next.js 14.2.5): compiles, lint + type check pass, `/live` generated (9.46 kB page).
- `/live`: opens the tracking WS on session start, shows a tracking-active banner, live `active_tracks`/`total_events`/`total_updates`, and a bounded recent tracking-events feed; the tracking WS is closed on stop/unmount.
- Fixed during verification: tracking metric/event types in `api.ts` now match the backend broadcasts exactly (`total_updates`, `removed_tracks`, `lost_tracks`, `events_by_type`, `track_event`).

## 16. Sample / dashboard data

- Unchanged this phase (carried from Phase 2: 4 sample videos, 5 cameras). No new seeders needed — tracking adds no persistent data.

## 17. Commands used

- `python -m py_compile` on all new/modified backend modules.
- `python -m pytest tests/test_tracking_unit.py -q` (12 PASS).
- `python -m pytest tests/test_tracking_integration.py -q` (10 PASS).
- `python -m pytest tests/test_tracker.py tests/test_detection_unit.py tests/test_regression_phase1.py tests/test_tracking_unit.py` (44 PASS).
- `python -m pytest tests --ignore=tests/test_evaluation.py --deselect <flaky>` → 193 passed, 6 skipped.
- `npm run build` (frontend).

## 18. Issues encountered and resolved during Phase 3

| Issue | Resolution |
|---|---|
| DetectionObject vs tracker dict contract mismatch (would silently disable tracking in production) | Adapter at the integration seam + a test covering the exact handoff (Fix 3.1) |
| `active_tracks` reported cumulative updates instead of a live count | Pipeline snapshot derives live count from the tracker; counter preserved as `active_updates` (Fix 3.2) |
| Tracking not initialized when detection is disabled by config | Intentional: tracking consumes detection results; the disabled path is asserted in a test |
| Frontend types diverged from the backend broadcast | Aligned `api.ts` types + `page.tsx` handlers to actual messages |

## 19. Pre-existing / environment issues (NOT Phase 3 regressions)

- ffmpeg/ffprobe NOT installed → video processing cannot reach COMPLETED (carried from Phase 2).
- MinIO and Qdrant down → in-memory/fallback paths (carried from Phase 1/2).
- `data/evaluation/benchmark.jsonl` missing → 6 pre-existing evaluation failures.
- Windows `time.monotonic` resolution makes the 1 ms guardrails test flaky.

## 20. Honest limitations / NOT TESTED

- **REAL-DEVICE / REAL-CAMERA tracking: NOT TESTED** (carried from Phases 1–2; no physical device on hand).
- **Real YOLO model feeding the tracker: NOT TESTED** (synthetic detections only).
- **Real-network WS delivery, TURN/NAT/ICE: NOT TESTED** (unchanged from Phases 1–2).
- **Tracking accuracy on real footage (ID persistence, occlusion, re-acquire): NOT EVALUATED** — Phase 3 proves plumbing/contracts.
- **GPU / large-scene throughput: NOT MEASURED** (CPU host; tracking math is negligible next to upstream YOLO).

## 21. Phase 4 prerequisites — high priority

1. Validate REAL-DEVICE WebRTC end-to-end on physical hardware (unchanged blocker since Phase 1).
2. Run real YOLO inference feeding the tracking pipeline on a footage dataset to validate ID persistence/occlusion behavior.
3. Install ffmpeg/ffprobe so uploaded videos reach COMPLETED (clips+detections) before tracking can be validated on stored video.
4. Add `data/evaluation/benchmark.jsonl` and replace the 1 ms guardrails deadline test with a resolution-safe value.

## 22. Phase 4 recommendations — medium priority

5. Persist aggregate tracking statistics/events (not per-frame rows) once storage is online; keep the `track_update`/`tracking_metrics` broadcast contract stable.
6. Throttle `tracking_metrics` broadcasts to ≤1/s per session if realtime throughput demands it (currently emitted each frame feed; the bounded queue absorbs bursts).
7. GPU realtime: set `YOLO_DEVICE`, raise `DETECTION_QUEUE_SIZE`/`imgsz` — tracking math is a negligible fraction of per-frame cost.

## 23. Verification summary

| Item | Result |
|---|---|
| Tracking unit tests | 12/12 PASS |
| Tracking integration tests | 10/10 PASS |
| Targeted regression (tracker + detection unit + phase1 regression) | 44/44 PASS |
| Full suite (excl. evaluation + pre-existing flaky) | 193 PASS, 6 skipped, 0 failed |
| Pre-existing failures | evaluation (missing dataset) + 1 flaky 1 ms timing test — both pre-existing, unrelated to Phase 3 |
| Frontend build | PASS (`/live` generated) |
| Real-device / real-camera / real-YOLO-to-tracker E2E | NOT TESTED |

## 24. Verdict

### READY FOR PHASE 4

The Phase 3 deliverable — a modular per-session multi-object tracking layer consuming the Phase 2 detection contract with persistent visual IDs, absolute-pixel motion metrics, event detection, bounded/thread-safe internals, a dedicated RBAC WebSocket, live status fields, and frontend surfacing — is implemented and verified by 22 new tests (12 unit + 10 integration) plus a clean 193-PASS full-suite run. The integration tests caught and fixed two real production bugs (the DetectionObject→tracker seam and the live active-tracks count), which is precisely the verification Phase 3 required. The same honest caveats as Phases 1–2 remain (no physical device, no real-camera/real-network E2E, no real-YOLO-to-tracker validation, no accuracy evaluation on real footage) and are listed as Phase 4 prerequisites; none blocks Phase 4, which should consume the `TrackUpdate`/`TrackingEvent`/`TrackingMetricsOut` contracts for event aggregation, storage, VLM analysis, RAG, and reporting.

## 25. Delta vs Phase 2 report

Added: whole `tracking/` module (7 files), 22 Phase 3 tests, tracking lifecycle + detection→tracking seam in the live manager, tracking WebSocket + status-schema fields, `TRACKING_*` config, frontend tracking WS/banner/metrics/events feed. Caveats carried forward unchanged: no physical device, no GPU, no ffmpeg, MinIO/Qdrant offline, missing `benchmark.jsonl`; plus a newly-noted pre-existing flaky 1 ms timing test and an honest "no real-model-to-tracker run" this phase. Verdict stays green because the Phase 3 wiring is proven at the seam level by integration tests (which caught the two blocking bugs) and every real-hardware limitation is explicitly enumerated rather than hidden.