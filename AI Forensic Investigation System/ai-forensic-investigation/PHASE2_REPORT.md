# Phase 2 Report — Real-Time YOLO Object Detection Layer

Date: 2026-09-11
Scope: Phase 2 of the AI Forensic Investigation System — fix the three Phase 1 issues (thread-safe status publishing, signaling-teardown scoping, ICE candidate ordering), add a modular per-session YOLO (Ultralytics) detection layer consuming only sampled frames via a non-blocking bounded queue, expose detections to the frontend over a dedicated WebSocket with a bounding-box canvas overlay, seed the dashboard with public sample videos, and verify with unit/integration/regression/real-model/performance tests. Tracking/events/VLM/RAG/reports remain OUT of scope; detection schemas are the stable contract for Phase 3+.

---

## 1. Implemented functionality

| Component | Description | Location |
|---|---|---|
| Detection schemas | Stable Pydantic contract: `BoundingBox` (absolute pixel `x1,y1,x2,y2`, NOT normalized), `DetectionObject`, `DetectionFrame` + compact `as_broadcast()` for the WS | `backend/app/detection/schemas.py` |
| Detection engine | Wraps Ultralytics YOLO behind a small interface; loads once per config (registry `get_engine()`/`clear_engines()`); `RLock` serializes inference so sessions share one model concurrency-safely; typed errors (`ModelNotFoundError`, `InvalidFrameError`, `InvalidModelError`, `DetectionError`); frame coercion (`as_bgr_uint8`) | `backend/app/detection/engine.py` |
| Torch 2.6+ fix | Idempotently patches `torch.load(weights_only=False)` so ultralytics 8.2.x legacy pickles load (`UnpicklingError: Weights only load failed` otherwise) | `backend/app/detection/engine.py` |
| Detection metrics | In-memory only (no DB rows per frame): input/sampled/processed/detection FPS (EMA), latency avg/max, totals, drops, inference errors, live queue depth; injectable clock; thread-safe | `backend/app/detection/metrics.py` |
| Bounded worker | Per-session daemon-thread consumer; bounded condition-queue; **newest-wins** backpressure (drop old stale frame when full, counted); `drain`/`discard` stop modes; one failed inference never kills the worker | `backend/app/detection/worker.py` |
| Detection pipeline | Binds engine (shared) + metrics + worker (per session) + bounded recent-results ring; `build()` from registry; session-isolated | `backend/app/detection/pipeline.py` |
| Lifecycle integration | Detection starts on `LIVE` (idempotent) and stops on terminal states; model-init failure is per-session and non-fatal (`detection_error`); `manager.clear()`/`stop()` release worker threads | `backend/app/live/manager.py` |
| Ingestion hook | New `on_input` / `on_sampled` callbacks on `FrameIngestion` route raw→metrics and sampled→YOLO without coupling | `backend/app/live/ingestion.py` |
| Detection WS | `/live/cameras/{id}/ws/detections` — JWT auth + LIVE_ROLES; sends `detection_status`, `detection` frames (absolute-pixel bboxes), `detection_keepalive`; unsubscribes on disconnect | `backend/app/api/live.py` |
| Status schema | `LiveStatusOut` extended: `detection_enabled`, `detection_error`, `detection_metrics`, `detection_recent_count` | `backend/app/schemas/live.py`, `frontend/lib/api.ts` |
| Config | `YOLO_DETECTION_ENABLED`, `YOLO_CONF_THRESHOLD` (0.30), `YOLO_IOU_THRESHOLD` (0.45), `YOLO_DEVICE` (cpu), `YOLO_IMGSZ` (640), `YOLO_MAX_DETECTIONS` (100), `DETECTION_QUEUE_SIZE` (8), `DETECTION_RECENT_FRAMES` (200) | `backend/app/core/config.py` |
| Frontend overlay | `/live` page draws live bounding boxes + class/confidence labels on the video via an absolutely-positioned canvas (DPR-scaled, resize-aware), detection FPS/objects badge, detections tile in stats | `frontend/app/live/page.tsx`, `frontend/lib/api.ts` |
| Sample-data seeder | Downloads public sample videos (Sintel/BBB trailers, CC test clips — GTV bucket 403'd, sources swapped) with stdlib only; auto-registers 5 CCTV/OTHER cameras + uploads 4 videos through the real API; `--process` flag triggers ffmpeg processing | `backend/scripts/seed_sample_data.py` |

Requirements honored: inference never blocks the FastAPI event loop (dedicated thread); bounded queue + documented drop policy; detection only on SAMPLED frames; session isolation via per-session worker/metrics over a shared locked engine; no DB rows per frame/detection; no migration needed (detections are in-memory); RBAC applied to the detection WS.

## 2. Fixes for the three Phase 1 issues

| # | Phase 1 issue | Fix | Verified by |
|---|---|---|---|
| 1.1 | Signaling teardown killed unrelated sessions (`finally` always `manager.stop`) | `owns_session` flag (True only when THIS socket created the runtime): an unrelated signaling WS only closes its WebRTC handle and never transitions REST-managed sessions; WebSocketDisconnect transition is also ownership-guarded; `_close_webrtc` suppresses connection-state callbacks so `pc.close()` can't flip a live session to DISCONNECTED | `test_unrelated_signaling_disconnect_keeps_rest_session`, `test_signaling_owned_session_cleaned_up_on_disconnect` |
| 1.2 | ICE-candidate-before-offer race / spurious errors; ALSO latent crash: `candidate_from_sdp` called with the old 3-arg signature invalid under aiortc 1.15.0 | Buffer candidates until remote description applied; flush after `setRemoteDescription`; malformed candidates still raise at trickle time; buffer cleared on close | `TestICEBuffering` (6 scenarios: before-offer buffering, offer-then-direct, multiple, invalid→raises, close clears, flush) |
| 1.3 | `asyncio.Queue.put_nowait` from threadpool/threads | `_Subscriber` (queue + owning loop) + `loop.call_soon_threadsafe` publish; drop-oldest on full; same mechanism for detection subscribers | `test_metrics_thread_safety` (metrics), existing status-WS tests + new detection-WS streaming tests |

## 3. Files added or modified

- **New:** `backend/app/detection/` (`__init__.py`, `schemas.py`, `engine.py`, `metrics.py`, `worker.py`, `pipeline.py`); `backend/scripts/seed_sample_data.py`; `tests/conftest.py` edit (below), `tests/detection_fakes.py`, `tests/test_detection_unit.py`, `tests/test_detection_integration.py`, `tests/test_detection_real_yolo.py`.
- **Modified:** `backend/app/live/manager.py`, `backend/app/live/ingestion.py`, `backend/app/live/webrtc.py`, `backend/app/api/live.py`, `backend/app/schemas/live.py`, `backend/app/core/config.py`, `tests/conftest.py` (default `YOLO_DETECTION_ENABLED=false` so the suite never loads the model), `frontend/app/live/page.tsx`, `frontend/lib/api.ts`.
- No Alembic migration required (all detection state is in-memory).

## 4. Dependencies

- **New dependencies:** none — `ultralytics==8.2.57` already pinned in `requirements.txt`; `torch 2.14.0+cpu` already installed.
- Verified ecosystem versions: `aiortc 1.15.0`, `fastapi`, `next 14.2.5`, Python 3.11, CUDA unavailable (CPU-only host).

## 5. Environment facts recorded

- `torch.cuda.is_available() == False` — all inference numbers are CPU.
- Model weights: `backend/yolov8n.pt` (also `D:\Github\Generative-Ai\yolov8n.pt`), COCO-80 classes.
- Torch 2.6+ weights_only patch verified on the real model: load ~30–50 ms.

## 6. Real YOLO inference results (CPU, yolov8n, imgsz 640, conf 0.30)

- Model load: 31–47 ms.
- Warm-up first inference (random 640×480 noise): ~4.0 s (auto batches / cudnn tuning).
- Steady state @ 640×480 noise: **~615 ms/frame**.
- Live simulation feed (synthetic frames): **avg 138.5 ms/frame**.
- 0 detections on noise frames (expected); engine never crashed across 3+ repeated runs.
- CPU throughput bounds real-time use to roughly 1.5–7 FPS at 640×480; GPU/TensorRT would be the Phase 4+ path for high-res realtime.

## 7. Live end-to-end smoke (running backend, simulation transport, REAL YOLO)

- `POST /live/cameras/6/start` (simulation) → `LIVE`, session id 22.
- Polled status: `frames_received=134, frames_sampled=68, detection_enabled=true, detection_error=null, detection_recent_count=52`; metrics `processed=52, detections=0, drops=5, errors=0, latency_avg=138.52ms`. Bounded-queue drops observed under the 5 FPS simulated load → backpressure behaving as designed.
- `POST /live/cameras/6/stop` → `OFFLINE`, `detection_enabled=false`; worker released.

## 8. New unit tests (`tests/test_detection_unit.py` — 20, all PASS)

Schemas/serialization; bounding-box constructor/validation; `as_bgr_uint8` coercion (grayscale/RGB/passthrough); metrics EMA rates + totals + avg/max latency under a fake clock; queue depth semantics; worker: consumed results, bounded-queue evictions counted as drops, stop modes `drain` vs `discard`, inference-error resilience (worker keeps running), throughput-under-load stays ≤ `maxsize`; pipeline recent-results ring (drop-oldest beyond `DETECTION_RECENT_FRAMES`) and input-vs-sampled metric routing.

## 9. New integration tests (`tests/test_detection_integration.py` — 16, all PASS)

Detection lifecycle (starts on LIVE, stops on terminal, idempotent); activation state + metrics surfaced through live status REST; disabled-by-config (no engine touch, `detection_enabled=false`); model soft-fail (bad model path → session stays LIVE, `detection_error` set, WS still pushes status); two-camera session isolation over a single shared engine (correct per-session counters); detection WS: streams results with auth_ok→status→detections, RBAC 403 for REVIEWER, unsubscribes on client disconnect; Fix 1.1 regressions; `TestICEBuffering` (6 scenarios for Fix 1.2).

## 10. Real-model tests (`tests/test_detection_real_yolo.py` — 2, all PASS)

Real `yolov8n.pt` loads via the patched bridge; `infer` on a real `np.ndarray` BGR frame returns a valid `DetectionFrame`; a noise frame yields zero detections without exceptions (warm-up + steady-state latency recorded in §6).

## 11. Phase 1 regression tests (48, all PASS)

`test_live_pipeline.py` (18), `test_live_api.py` (14), `test_live_ws.py` (8), `test_regression_phase1.py` (8) — all unchanged behavior remains green, including the signaling/status WS and WebRTC SDP error paths.

## 12. Full-suite result

`python -m pytest tests --ignore=tests/test_evaluation.py`: **168 passed, 10 skipped (pre-existing), 0 failed** in ~88 s. The Phase 1 fixes (#1.1–#1.3) introduced no regressions; no detection test leaks threads (workers joined via `manager.clear()` teardown).

## 13. Pre-existing failures (NOT caused by Phase 2)

`tests/test_evaluation.py`: 6 FAIL / 8 PASS — depends on `data/evaluation/benchmark.jsonl`, which is absent from the repo. Same as Phase 1 report. Requires a benchmark dataset in a later phase.

## 14. Backpressure / performance regression checks

- Sustained 3,000-submit load with a slow consumer: queue length ≤ `maxsize`, drops counted, worker keeps processing, no unbounded memory growth.
- Metrics lock-guarded under 6 threads × 200 events → exact totals, no errors.
- Worker now reports consume-time queue depth (live metric), not submit-time.

## 15. Frontend verification

- `npm run build` (Next.js 14.2.5): compiles, lint + type check pass, `/live` generated.
- Fixed a type error during verification: detection WS message union is `LiveDetectionStatusEvent | LiveDetectionFrame` (was an impossible intersection in `api.ts`).
- `DetectionOverlay` canvas: absolute-pixel bboxes scaled to the video container, DPR-aware, labels + confidences; detections stat tile wired to the detection WS.

## 16. Sample/dashboard data

- `backend/scripts/seed_sample_data.py` run against the live backend: cameras `CCTV_Retail_Floor`(2), `CCTV_Parking`(3), `CCTV_Plaza`(4), `CCTV_Street_Corridor`(5), `CCTV_Lobby`(6); 4 public sample videos uploaded via the real API (`video_id` 1–4: Sintel trailer, BBB trailer, BBB 10 s clip, sample_640x360).
- `GET /dashboard/stats` now reports `total_videos=4` with 4 recent videos.
- Seeder admin user `sample.data@forensics-demo.com` left in the dev DB for demos.
- GTV sample bucket returns HTTP 403; swapped to verified public mirrors (media.w3.org, test-videos.co.uk, filesamples.com). Seeder is stdlib-only (no new dependency).

## 17. Commands used

- `python -m py_compile` on all modified/new backend modules.
- `python -m pytest tests/test_detection_unit.py -q`, `tests/test_detection_integration.py -q`, `tests/test_detection_real_yolo.py -q -s`.
- `python -m pytest tests/test_live_pipeline.py tests/test_live_api.py tests/test_live_ws.py tests/test_regression_phase1.py -q` (Phase 1 regression).
- `python -m pytest tests --ignore=tests/test_evaluation.py` (full suite), `python -m pytest tests/test_evaluation.py` (pre-existing failures).
- `npm run build` (frontend).
- Backend restart: killed PID 26684 → uvicorn PID 23316 on `:8000` (health 200).
- `python scripts/seed_sample_data.py --base-url http://localhost:8000` (sample data).

## 18. Issues encountered and resolved during Phase 2

| Issue | Resolution |
|---|---|
| Torch 2.14 CPU rejects legacy YOLO pickles (`weights_only`) | Engine-level idempotent `torch.load(weights_only=False)` patch (verified on real model) |
| `candidate_from_sdp` signature mismatch (aiortc 1.15) — latent Phase 1 bug that would crash on the first real trickle | Single-arg API + explicit `sdpMid`/`sdpMLineIndex` |
| `fps_target=5` decimation confused bulk test feeds (only ~half the frames sampled) | Tests feed frames ≥ 1.0 s apart so every frame is sampled |
| Bounded queue legitimately drops stale frames during bulk submit — a test asserted 12/12 | Tests feed-and-wait; drop policy explicitly re-tested |
| Unrelated signaling WS closing flipped a REST session to DISCONNECTED (found by new regression test) | `owns_session` guard + suppressed pc state callbacks during deliberate close |
| Queue-depth metric reflected submit-time only | Worker reports consume-time depth |
| GTV sample bucket 403 | Swapped to verified public mirrors |
| jsonl/openapi confusion over `/videos` response shape | Confirmed plain `VideoOut[]`; seeder reads it directly |

## 19. Pre-existing / environment issues (NOT Phase 2 regressions)

- ffmpeg/ffprobe are NOT installed → video processing to COMPLETED fails with `WinError 2` at `ffprobe_metadata`. Uploads and dashboard listing work; only the `process_video_job` stage is blocked. A Phase 3 prerequisite.
- MinIO and Qdrant are down — storage/vector fallbacks in use (unchanged from Phase 1).

## 20. Honest limitations / NOT TESTED

- **REAL-DEVICE WebRTC end-to-end: NOT TESTED** (carried from Phase 1 — no physical device on hand). Highest-risk open item in the project.
- Real-network ICE/TURN/NAT, actual peer media delivery, and frame decode on mobile hardware: NOT TESTED.
- YOLO throughput on GPU / production server: NOT TESTED (CPU numbers only, §6).
- Overlay pixel-alignment on mirrored/rotated phone video not validated on hardware.
- Detection accuracy (mAP) on real evidence footage: NOT EVALUATED — Phase 2 is transport/plumbing; accuracy belongs to the tracking/event phases.

## 21. Phase 3 prerequisites — high priority

1. Validate real-device WebRTC on physical hardware (phone ↔ server) — unchanged blocker since Phase 1.
2. Install ffmpeg/ffprobe (host or Docker) so uploaded videos reach COMPLETED (clips+detections); without it ingestion→retrieval cannot finish.
3. Add `data/evaluation/benchmark.jsonl` to turn the 6 pre-existing `test_evaluation.py` failures green.

## 22. Phase 3 recommendations — medium priority

4. For GPU realtime: set `YOLO_DEVICE`, raise `DETECTION_QUEUE_SIZE`/`imgsz` — the shared-engine/per-session-worker design supports concurrent sessions on one model.
5. Persist detections in a later phase by extending the `DetectionObject` schema — do NOT change the absolute-pixel bounding-box convention (documented in `schemas.py`).

## 23. Verification summary

| Item | Result |
|---|---|
| Phase 2 fixes 1.1–1.3 | PASS (dedicated regression + integration tests) |
| Detection unit tests | 20/20 PASS |
| Detection integration tests | 16/16 PASS |
| Real YOLO model tests | 2/2 PASS |
| Phase 1 regression suites | 48/48 PASS |
| Full suite (excl. evaluation) | 168 PASS, 10 pre-existing skips |
| Pre-existing evaluation failures | 6 (unchanged from Phase 1) |
| Frontend build | PASS |
| Live E2E smoke (real YOLO) | PASS (processed 52 frames, drops counted, clean stop) |
| Sample dashboard data | PASS (4 videos, 5 cameras) |

## 24. Verdict

### READY FOR PHASE 3

All Phase 2 deliverable items are implemented and verified: the three Phase 1 fixes, a modular YOLO detection layer on sampled frames over a bounded non-blocking queue, session isolation over a shared locked model, detection WebSocket + frontend overlay, and sample dashboard data — proven by 38 new tests plus green Phase 1 regression and full-suite runs, and by a live end-to-end smoke against the running backend with the real model. The one honest caveat (real-device WebRTC, NOT TESTED) is unchanged from Phase 1 and is listed as a Phase 3 prerequisite; it does not gate Phase 3, which should consume the `DetectionFrame`/`DetectionObject` contract for tracking, events, VLM analysis, RAG, and reports.

## 25. Delta vs Phase 1 report

Added: whole `detection/` module (6 files), 3 Phase 1 fixes, 38 Phase 2 tests (+46 lines of conftest fixture support), detection WS + status-schema fields, frontend overlay + API types, sample seeder + 4 sample videos/5 cameras in dev DB. Unchanged caveats: no physical device, no GPU, no ffmpeg, MinIO/Qdrant offline, missing `benchmark.jsonl`. Verdict remains green because the prior phase's actionable recommendations (seeder data; evaluation dataset) are either delivered (seeder) or explicitly queued for Phase 3 (`benchmark.jsonl`), and the real-device test cannot be performed in this environment.