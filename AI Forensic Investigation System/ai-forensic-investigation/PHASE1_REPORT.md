# Phase 1 Report — Real-Time Mobile Camera (WebRTC) Live Monitoring

Date: 2026-09-11
Scope: Phase 1 of the AI Forensic Investigation System — real-time ingestion from a mobile device camera over WebRTC, feeding sampled frames into an in-memory rolling buffer with real-time status, integrated with the existing Camera/RBAC/Audit/Alembic stack.

---

## 1. Implemented functionality

| Component | Description | Location |
|---|---|---|
| Rolling frame buffer | Bounded in-memory ring; time-window (15 s) + max-frames (150) eviction, configurable; concurrency-safe; `frames_between` / `snapshot` queries | `backend/app/live/rolling_buffer.py` |
| Frame sampler | Decimates source stream to a configurable target rate (default 5 FPS) | `backend/app/live/sampler.py` |
| Frame ingestion | Source-FPS cap, per-frame size guard (4 MB), rate-cap burst rejection, routing to sampler/buffer | `backend/app/live/ingestion.py` |
| Live camera source | Thin transport-agnostic push interface used by the session runtime | `backend/app/live/source.py` |
| WebRTC receive path | aiortc-based `RTCPeerConnection`; server is a receive-only answerer; browser is the sender; re-pairs connection if closed between offer and answer; exposes `WebRTCNotAvailable` when aiortc/av missing | `backend/app/live/webrtc.py` |
| Simulation transport | `FrameSimulationFeeder` injects synthetic frames at the target rate for dev/demo/tests; starts `LIVE` immediately | `backend/app/live/synthetic.py` |
| Session manager | Singleton; one active session per camera (`ActiveSessionError` → 409); state machine `CONNECTING → LIVE → STOPPING → COMPLETED/DISCONNECTED/ERROR` + camera `is_live`/`stream_status`; DB persistence throttled (~1/s) via `SessionLocal` | `backend/app/live/manager.py` |
| Live REST API | `POST /live/cameras/{id}/start`, `POST /live/cameras/{id}/stop`, `GET /live/cameras/{id}/status`, `GET /live/sessions`; RBAC `ADMIN`/`SECURITY_OFFICER`/`INVESTIGATOR`; audit logging | `backend/app/api/live.py` |
| Signaling WebSocket | `/live/cameras/{id}/ws/signaling` — first-message JWT auth + role check; `offer` / `trickle` / `bye` / `ping`; ice-candidate relay; marks `LIVE` on `connectionstatechange == connected` | `backend/app/api/live.py` |
| Status WebSocket | `/live/cameras/{id}/ws/status` — any authenticated user; pushes buffer snapshot plus state transitions, and `OFFLINE` with no active session | `backend/app/api/live.py` |
| Data model | `Camera` extended (`camera_type`, `stream_source`, `is_live`, `stream_status`); new `CameraSession` (`camera_sessions` table) | `backend/app/database/models.py` |
| Migration | Alembic `0005_phase1_live` (down_revision `0004_part4`) — applied to PostgreSQL | `backend/alembic/versions/0005_phase1_live.py` |
| Config | `LIVE_SESSION_FPS`, `LIVE_BUFFER_WINDOW_SECONDS`, `LIVE_BUFFER_MAX_FRAMES`, `LIVE_SOURCE_FPS_CAP`, `LIVE_MAX_FRAME_BYTES` | `backend/app/core/config.py` |
| Frontend | `/live` page: mobile-camera registration (MOBILE type), transport select, `getUserMedia` preview, `RTCPeerConnection` addTrack + trickle + offer, front/back camera switch (replaceTrack), status WS subscription, per-camera error handling (`NotAllowedError`/`NotFoundError`/`NotReadableError`), active-session list | `frontend/app/live/page.tsx`, `frontend/lib/api.ts`, `frontend/components/app-header.tsx` |

Requirements honored: signal handling is kept separate from frame processing (dedicated signaling WS vs. server-side aiortc receive loop + status WS); ingestion is fully independent of YOLO/analytics; sampling and buffer bounds are configurable; no secrets in logs or signaling payloads.

## 2. Error-scenario coverage (verified by tests)

| # | Scenario | Result |
|---|---|---|
| 1 | Start/status without token | 401 — PASS |
| 2 | Start/stop as non-privileged role (REVIEWER) | 403 — PASS |
| 3 | Signaling WS without/invalid token | rejected + disconnect — PASS |
| 4 | Signaling WS as non-privileged role | error + disconnect — PASS |
| 5 | Start on missing camera | 404 — PASS |
| 6 | Signaling on missing camera | error — PASS |
| 7 | Unsupported transport value | 422 — PASS |
| 8 | Double start on same camera | 409 — PASS |
| 9 | Stop with no active session | 409 — PASS |
| 10 | Invalid SDP offer | session ERROR surfaced — PASS |
| 11 | Oversized frame (> 4 MB) | rejected, not buffered — PASS |
| 12 | Source burst above FPS cap | rate-capped/dropped — PASS |

## 3. Verification results

### Backend tests (root `tests/`, `pytest.ini` testpaths=tests)
- Phase 1 suite: **48 tests, all PASS** (`test_live_pipeline.py` 18, `test_live_api.py` 14, `test_live_ws.py` 8, `test_regression_phase1.py` 8).
- Full suite excluding pre-existing broken file: **all PASS** (a few skips, unrelated to Phase 1).
- Pre-existing failures (NOT caused by Phase 1): `tests/test_evaluation.py` — depends on `data/evaluation/benchmark.jsonl`, which is **absent from the repo/Never committed** (`git ls-tree` confirms). These 6 tests fail on any checkout. Recommend Phase 2 add the benchmark dataset.

### Regression (existing functionality)
- 19-area backend regression run during the session: cameras (list/get/create + new fields), videos, dashboard, investigations, evidence, policies, reports, auth/RBAC, audit — all green with the Phase 1 additions.
- Alembic upgrade chain `0004_part4 → 0005_phase1_live` applied cleanly to PostgreSQL; schema columns present.

### Frontend build
- `next build` (Next.js 14.2.5): **compiles, lint + type check pass, 15 routes generated** (incl. `/live`).
- Fixed one type error during verification: `createCamera` request type in `frontend/lib/api.ts` now accepts `camera_type`/`stream_source`.

### Live end-to-end smoke (running backend, PostgreSQL, simulation transport)
- Register/login INVESTIGATOR → create MOBILE camera → `POST /live/cameras/1/start` → `LIVE`.
- ~4 s run: `frames_received=37, frames_sampled=19, frames_buffered=19` → effective ~5 FPS (target rate) ✔ decimation.
- `POST /live/cameras/1/stop` → `COMPLETED`; status afterwards `active=false, state=OFFLINE`; camera `is_live=false, stream_status=OFFLINE`.
- Persistence confirmed: `camera_sessions` row (status COMPLETED, transport simulation, frame counters, `started_by_user_id`) and updated camera flags on PostgreSQL.
- Note: the smoke run left test records in the dev DB (`Smoke Mobile Cam` camera, `smoketest_*` user, audit rows, session id 15).

## 4. Honest limitations / NOT TESTED

- **REAL DEVICE WebRTC end-to-end: NOT TESTED.** No physical mobile device was available to the agent. The aiortc receive path is implemented and unit/API/WS-tested (incl. SDP error handling), the browser sender path is implemented and builds, but phone↔server media round-trip over the real network has **not** been executed. This is the single highest-risk item for Phase 2 confidence.
- LAN/NAT/TURN configurations, ICE connectivity checks on a real network: NOT TESTED.
- Status endpoint retry/backoff behavior under sustained dropped-connection conditions: covered only at unit tolerance level.

## 5. Verdict

### READY FOR PHASE 2

— with the explicit caveat that **real-device WebRTC remains NOT TESTED** and must be validated on actual phone hardware before production rollout of the live-camera feature. All Phase 1 functional requirements, RBAC, error handling, pipeline, persistence, migrations, and frontend build are implemented and verified; no Phase 1 regressions were introduced.