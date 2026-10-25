# FINAL SYSTEM REPORT — AI Forensic Investigation System

**Date:** 2026-09-27
**Scope:** laptop-webcam live integration + final verification of Phases 5–8
**Verdict:** `FINAL STATUS: NOT READY` — one blocker: the physical webcam chain is
**NOT TESTED** in this environment (no capture device is reachable from the
Docker container). Everything else is verified against the real services.

> Nothing in this report is a mock result. Where a check could not run it is
> reported as `NOT TESTED` / `ENVIRONMENT FAILURE`, never as `PASS`.

---

## 1. Verification matrix (real services)

| Component | Status | Evidence |
|---|---|---|
| PHASE 5 — Evidence / Storage | **PASS** | PostgreSQL 15.19, 10/10 tables, alembic head `0008_phase8_forensics`, MinIO `forensics-frames` + `forensics-reports` PUT/GET/EXISTS/SHA-256 match, missing-object raises, corrupt bytes detected, duplicate PUT idempotent, **real Qdrant** insert/search/metadata-filter/negative-filter/delete, dims 384 |
| PHASE 6 — Video RAG | **PASS** | 103 checks, 0 failures (`verify_video_rag_demo.py` + `verify_demo_investigation.py` against the live API) |
| PHASE 7 — LangGraph Agent | **PASS** | full graph, evidence-scoped retrieval, UNKNOWN abstention, review state machine |
| PHASE 8 — Forensic Analysis | **PASS** | 46 checks, timeline/verification/gaps/contradiction + **real PDF** via ReportLab stored in MinIO |
| Test suite | **PASS** | 419 tests, 0 failures, 0 errors, 0 skipped (405 pre-existing + 14 new webcam tests) |
| Frontend build | **PASS** | `npm run build` clean, 20 routes |
| WEBCAM — device capture | **NOT TESTED (ENVIRONMENT FAILURE)** | no `/dev/video*` in the container; Docker Desktop does not pass a host camera through |
| WEBCAM — live ingest → RAG → LangGraph → report with **live camera frames** | **NOT TESTED** | depends on the capture above |
| VLM (real provider) | **NOT TESTED** | no external VLM credentials configured in this environment |

Reproduce with:

```bash
python backend/scripts/verify_final_system.py --base-url http://127.0.0.1:8000
```

---

## 2. Environment

| Item | Value |
|---|---|
| Host OS | Windows (PowerShell 5.1), Docker Desktop 29.8.0 |
| Container OS | `Linux-6.18.33.2-microsoft-standard-WSL2-x86_64` (glibc 2.41) |
| Python | 3.11.16 |
| OpenCV | 4.10.0 |
| PyTorch | 2.14.0+cu130 |
| **CUDA available** | **False** (`torch.cuda.is_available() == False`, 0 devices) → all inference ran on **CPU**; no GPU claim is made |
| PostgreSQL | 15.19 (Alpine 15.2.0) |
| MinIO | `RELEASE.2025-09-07T16-13-09Z` |
| Qdrant | `qdrant/qdrant:v1.9.4`, collection `video_evidence`, dims 384 |
| ReportLab | 4.2.5 (added — see §5) |
| YOLO model | `yolov8n.pt` (`YOLO_MODEL`), device `cpu`, imgsz 640 |
| VLM provider | none configured → `REAL VLM PROVIDER NOT TESTED` |
| LangGraph | `langgraph==1.2.11`, `langchain-core==1.6.1` |

`/health` at verification time: database `ok`, qdrant `backend=qdrant ok`,
storage `backend=minio ok`, evidence indexer `running=true total_indexed=113
total_failed=0`, live `active_sessions=0`.

---

## 3. What was implemented for the webcam

### 3.1 One capture implementation, two transport names

* **New** `backend/app/live/webcam_camera.py`
  * `LocalOpenCVCameraSource(CameraSource)` — the shared OpenCV capture thread
  * `WebcamCameraSource` — transport `webcam`, reads `WEBCAM_*` defaults
* **Refactored** `backend/app/live/usb_camera.py` — `UsbCameraSource` is now a
  4-line subclass supplying only `name="droidcam_usb"` + `settings_prefix="DROIDCAM"`.
  No second pipeline, no duplicated YOLO, no duplicated tracking.
* Hardening: `connect()` reads one real frame before reporting `opened=true`
  (a non-existent device otherwise reports `isOpened()==True`), and reconnects are
  bounded by `WEBCAM_MAX_RESTARTS`.

### 3.2 API

`POST /live/cameras/{camera_id}/start` now accepts
`{"transport": "webcam", "device_index": 0, "fps_target": 10}`.
`webrtc`, `simulation`, `file`, `droidcam_usb` are unchanged. An unopenable
device returns **HTTP 503** and no session is created.

### 3.3 Health payload

`source, device_index, opened, alive, running, frames_read, dropped_frames,
restarts, last_frame_at, error` — surfaced through `/live/cameras/{id}/status`.

### 3.4 Frontend (`/live`)

* Source selector is now **Camera source** with explicit labels:
  *Phone WebRTC (real)*, *Laptop Webcam (real)*, *USB / DroidCam (real)*,
  *Simulation (synthetic)*, *Demo Video (not evidence)*.
* **Camera device** + **FPS** inputs for the local-camera transports.
* New live counter row: `CONNECTED/LIVE`, frames, dropped, restarts, measured
  FPS, detection count, track count, event count, evidence captured/indexed,
  VLM count, plus the real YOLO model/device and mean inference latency reported
  by the backend.
* `source_health` / `evidence_*` fields added to the `LiveStatus` type.

### 3.5 Verification scripts

| Script | Purpose |
|---|---|
| `verify_webcam.py` | opens the real device: `--probe` lists indices 0–3, `--device/--seconds/--fps` runs the capture test with resolution/FPS/continuity/release checks |
| `verify_live_webcam.py` | full API-driven chain webcam → session → ingest → sampling → YOLO → tracking → events → evidence → PostgreSQL → MinIO → Qdrant → VLM; fails loudly with the exact blocker if the device cannot be opened |
| `verify_final_system.py` | consolidated phase + webcam matrix, writes `data/verification_results.json`, prints `FINAL STATUS: READY|NOT READY` |
| `verify_phase5/6/7/8.py` | per-phase entry points (Phase 5 also verifies MinIO/Qdrant/PostgreSQL/alembic directly) |
| `gen_cases_index.py` | rebuilds the demo `cases.json` index from the real downloaded dataset |

---

## 4. Why the physical chain is NOT TESTED here

```text
$ docker exec forensic-backend python scripts/verify_webcam.py --probe
WEBCAM PROBE (indices 0..3)
  no capture device produced a frame on indices 0..3
RESULT: NO DEVICE

$ docker exec forensic-backend ls /dev/video*
ls: cannot access '/dev/video*': No such file or directory
```

Docker Desktop's WSL2 backend does not expose a Windows capture device to
containers. Consequently, **physically unverified** steps are: real webcam
frames → real YOLO on live frames → tracking → motion events → evidence capture
→ RAG over live evidence → LangGraph investigation → timeline → finding → human
review → PDF, and the "place objects in front of the camera" detection
acceptance (§14 of the brief) could not be performed by an automated agent.

To close this blocker on the host:

```bash
cd backend
python scripts/verify_webcam.py --probe
python scripts/verify_webcam.py --device 0 --seconds 10
uvicorn app.main:app --reload            # host-native backend
python scripts/verify_live_webcam.py --base-url http://127.0.0.1:8000 --device 0 --seconds 45
```

---

## 5. Defects found and fixed during verification

| # | Defect | Fix |
|---|---|---|
| 1 | **ReportLab was not installed** → the "PDF" report silently degraded to markdown, so no PDF was ever produced | `reportlab==4.2.5` added to `backend/requirements.txt`; PHASE 8 now renders a real PDF (46/46 checks) |
| 2 | `GET /demo/dataset` raised `AttributeError` → HTTP 500 because the manifest's `thumbnails` list can contain `null` | `app/api/demo.py` skips non-dict entries; the downloader no longer writes `null` thumbnail entries |
| 3 | `verify_demo_investigation.py` asserted 6 videos / 5 cases while the licensed dataset has 10 | assertions updated to the documented 10-video / 10-case set |
| 4 | `droidcam_usb` was a separate ~200-line capture implementation | collapsed into `LocalOpenCVCameraSource`; behaviour preserved |
| 5 | `usb_camera.connect()` trusted `isOpened()`, so a non-existent device looked healthy | both transports now read a real frame before reporting `opened=true` |
| 6 | Live status never reported the real YOLO model/device | `DetectionEngine.model_info()` + surfaced via `detection_metrics` (reports the *actual* torch device, never an assumed CUDA) |
| 7 | Demo `cases.json` absent from a fresh checkout | `gen_cases_index.py` rebuilds it from the downloaded dataset |

### Known pre-existing condition (not fixed, reported)

Running `verify_final_system.py` **twice without an intervening
`reset_demo_database.py`** makes the Phase 5 integrity check report orphaned
references, e.g. `analysis #6: 'EVD-DEMO-…' does not exist`. Cause:
`seed_demo_evidence._wipe_demo_evidence()` deletes every `EVD-DEMO-%` evidence row
but leaves the `forensic_analyses` rows that reference them. This is demo-reset
tooling behaviour, not a live-pipeline defect — evidence created by a live
session is never deleted. A clean `reset → seed → verify` cycle reports Phase 5
**PASS**. It is called out here rather than hidden.

---

## 6. Regression evidence

```text
pytest      : 419 tests, 0 failures, 0 errors, 0 skipped
npm run build : clean (Next.js production build, 20 routes)
PHASE 5     : PASS
PHASE 6     : PASS (103 checks)
PHASE 7     : PASS
PHASE 8     : PASS (46 checks, reportlab)
WEBCAM      : NOT TESTED (ENVIRONMENT FAILURE - no device in container)
FINAL STATUS: NOT READY
```

**Blocker (exact):** the laptop webcam is not reachable from the verification
environment (`/dev/video*` absent in the container), so the physical chain
`REAL FRAME → REAL YOLO → … → REAL REPORT` has no evidence of success and is
recorded as `NOT TESTED`.

---

## 7. Final status classification

| Area | Classification |
|---|---|
| `webcam` transport (code + tests) | **IMPLEMENTED, VERIFIED (unit/integration)** |
| Live Console webcam controls | **IMPLEMENTED, VERIFIED (build)** |
| Phases 5–8 against real PG/MinIO/Qdrant | **VERIFIED** |
| Physical webcam → report chain | **NOT TESTED** |
| Real VLM provider | **NOT TESTED** |
| GPU inference | **NOT APPLICABLE** — no CUDA device present; CPU used |

---

## 8. Addendum (2026-09-27): black preview / misaligned boxes — root cause and fix

**Symptom:** the laptop camera was open and objects were being detected, but the
console surface was black and the boxes covered only part of the screen.

**Root cause 1 — no preview at all for backend-owned captures.** The console
rendered the feed with a single `<video>` element, whose `srcObject` is only
ever set for WebRTC (and the pre-start `getUserMedia` preview). For
`webcam`/`droidcam_usb`/`file`/`simulation` the backend owns the camera, so
the element had no source and rendered black.

**Fix:** `GET /live/cameras/{id}/stream.mjpg` (`app/api/live.py` +
`mjpeg_frame_stream`) re-publishes the very frames that enter
`LiveSessionRuntime.ingest_frame` (`app/live/manager.py`:
`subscribe_preview`/`publish_preview`/`_encode_preview`) as
`multipart/x-mixed-replace`. The console uses an `<img>` for those transports
and keeps `<video>` for WebRTC. Encoding is skipped entirely when no client is
watching, so WebRTC cost is unchanged.

**Root cause 2 — overlay ignored `object-contain` letterboxing.** Boxes were
scaled to the full 16:9 container (`scale = rect / frame`), so on a 4:3 camera
(640x480) they were stretched horizontally onto the black pillar bars and no
longer matched the image. The overlay now computes the letterboxed content rect
from `frame_width`/`frame_height` and maps the absolute-pixel boxes onto the
image area, clamping label boxes at the top edge.

**Verification**

| Check | Result |
|---|---|
| MJPEG endpoint, live stack, simulation capture | **PASS** — 13 JPEG parts in ~2.2s, `multipart/x-mixed-replace`, 401 without token, decodable frames |
| `tests/test_live_preview_stream.py` | **PASS** — 11 tests (encode-only-when-watched, multipart framing, JPEG decode, queue cap 64, session end, 401/403/409 matrix) |
| Full suite | **PASS** — 430 tests, 0 failures (419 + 11) |
| `npm run build` | **PASS** |
| Frontend image rebuilt + `/live` served | **PASS** — bundle contains `stream.mjpg` |

Not verifiable by an automated agent: the physical picture on the laptop screen
(needs eyes on the device). The preview pipeline itself is proven by the checks
above because it is transport-agnostic — the same code path serves the webcam
frames.
