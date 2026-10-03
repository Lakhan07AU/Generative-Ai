# ARCHITECTURE.md — AI Forensic Investigation System

End-to-end architecture through Phase 9. Every stage is honest about what it
can and cannot assert; nothing below ever fabricates timestamps, identities, or
AI results.

## 1. System overview

```
   CCTV / upload                  live cameras
   (FFmpeg pipeline)              (WebRTC | simulation | file | droidcam_usb)
         │                              │
         ▼                              ▼
   ┌───────────────┐           ┌───────────────────┐
   │ Part 1 upload │           │ Live session      │  FrameIngestion → FrameSampler
   │ pipeline      │           │ (LiveCameraSource)│  → RollingFrameBuffer
   └──────┬────────┘           └─────────┬─────────┘
          │                              │ detection (YOLO) → tracking → VLM
          ▼                              ▼
   ┌──────┴──────────────────────────────┴─────────┐
   │ Evidence layer                                │
   │  ForensicEvidence (camera/video/clip provenance)│
   │  sha256 + storage object, Qdrant index         │
   └──────┬─────────────────────────────────────────┘
          ▼
   ┌───────────────────────────────────────────────┐
   │ Part 6 demo dataset / investigation retrieval │
   │ Part 7 controlled investigation agent          │
   │ Part 8 forensic analysis                        │
   │   correlation → timeline → verification →      │
   │   contradictions/gaps → multi-camera → report   │
   └───────────────────────────────────────────────┘
```

## 2. Media transports (live)

| Transport | Source | Used for |
|-----------|--------|----------|
| `webrtc` | aiortc receives peer track | physical mobile camera (signaling WS + status WS) |
| `simulation` | deterministic synthetic frames | dev/demo |
| `file` | OpenCV `cv2.VideoCapture` of a demo video | reproducible pipeline demo; path confined to `DEMO_DATA_DIR` |
| `droidcam_usb` | OpenCV capture from device index (DroidCam) | live USB/DroidCam camera |

All transports feed the same `LiveCameraSource` abstract adapter
(`app/live/source.py`). Phase 9 added the `CameraSource` base contract
(connect / read_frame / is_alive / health) so status screens treat every source
uniformly. USB source: `app/live/usb_camera.py`.

## 3. Evidence lifecycle

1. **Capture** — trigger frames from tracking events or VLM observations
   (`app/evidence/capture.py`). Optical data is downscaled JPEGs; originals never
   leave the buffer as raw bytes.
2. **Persist** — `ForensicEvidence` row with `camera_id/session_id`, frame refs,
   `sha256`, `storage_path` (`app/evidence/paths.py`).
3. **Index** — asynchronous `EvidenceIndexQueue` calls Qdrant
   (`app/evidence/indexer.py`). Status is honest: PENDING/INDEXING/INDEXED/FAILED
   with a reindex API. The queue is bounded (drop-oldest when full).
4. **Verify** — `scripts/verify_evidence_integrity.py` reconciles ledger vs
   storage bytes (SHA-256) vs vector points and flags orphaned references.

## 4. Investigation / forensic layers

- **Part 6** (`app/investigation/`, `app/ai/`): bounded retrieval caps
  (`RAG_MAX_CONTEXT_ITEMS`, `RAG_MAX_EVIDENCE_PER_EVENT`), embeddings dimension
  guarded.
- **Part 7** (`app/investigator/`): orchestrated agent with hard caps on steps,
  tool calls, evidence, seconds and per-step `top_k`; reviewable findings pause
  at `READY_FOR_REVIEW` for a human.
- **Part 8** (`app/forensic/`): deterministic, evidence-grounded analysis —
  correlation, chronological timeline, finding verification (OBSERVED /
  INFERRED / UNKNOWN / CONFLICTING / UNVERIFIED), contradiction + gap detection,
  multi-camera correlation, PDF report. Every claim carries `evidence_ids`.

## 5. Storage / vector backends (honest)

| Layer | Primary | Fallback | How it reports |
|-------|---------|----------|----------------|
| Database | PostgreSQL (Alembic head `0008`) | SQLite test file | `/health → database` |
| Vector | Qdrant (`video_evidence`, `policy_chunks`) | in-memory cosine store | `qdrant.backend_name()` |
| Objects | MinIO buckets | local `data/storage/` | `storage.backend_name()` |

`/health` (detailed per-component) and `/metrics` (Prometheus text) expose which
backend is actually in use so results are never mistaken for something else.

## 6. Modules (backend)

```
app/
├── main.py            FastAPI app + CORS + lifespan + SECRET_KEY guard
├── core/config.py     app settings (pydantic-settings)
├── api/               auth, cameras, videos, media, live, evidence, rag,
│                      policies, investigations, reports, dashboard, demo,
│                      investigation_search, investigator, forensics, health
├── auth/              security, deps (DB-role checks), rate_limit
├── audit/service.py   audit log for security-relevant events
├── database/          session, models (migrations in alembic/)
├── storage/service.py LocalStorageService / MinIOStorageService
├── ai/                provider, embeddings, qdrant_service
├── live/              source, manager, synthetic, video_feeder, usb_camera,
│                      rolling_buffer, census, detection, tracking, vlm, webrtc
├── evidence/          capture, paths, indexer
├── investigation/     retrieval UI behaviors
├── investigator/      agentic run orchestration
└── forensic/          correlation, timeline, verification, contradictions,
                       gaps, multi_camera, store, report
```

## 7. Frontend (frontend/)

Next.js 14 + TypeScript + Tailwind. Pages cover login/register, dashboard,
videos, video detail, cameras, live console (WAS: signaling/status/detections/
tracking/VLM), investigations, investigation detail, reports, evidence,
policy QA, demo, and admin. JWT stored in localStorage by `lib/api.ts`.

## 8. Verifiers and ops scripts (backend/scripts/)

| Script | Purpose |
|--------|---------|
| `reset_demo_database.py` | drop schema → `alembic upgrade head` → clear stores → seed |
| `backup_database.py` | `pg_dump` / SQLite copy |
| `verify_demo_dataset.py` | dataset + benchmark + stale artifacts |
| `verify_evidence_integrity.py` | ledger ↔ storage ↔ vector reconciliation |
| `verify_demo_investigation.py` | dataset + workflow (`--base-url` live) |
| `run_full_e2e.py` | dependency-gated full E2E (PASS / FAIL / NOT TESTED) |

## 9. Quality gates

- 39 backend test modules + hardening tests, all green (`python -m pytest -q`).
- Verification-critical behaviors are unit-tested: no-invention of timestamps,
  low-resolution frames never become OBSERVED, conflicts flagged not resolved,
  unanswerable runs report honestly.
- Baseline ordering and the 11-scenario benchmark dataset
  (`data/evaluation/benchmark.jsonl`) are deterministic and reproducible.
---

## 16. Laptop Webcam Transport (`webcam`)

The live console gained a real local-camera transport alongside the existing
`webrtc` / `simulation` / `file` / `droidcam_usb` options. There is
**one** OpenCV capture implementation in the codebase:

``text
webcam                droidcam_usb
   \                   /
    LocalOpenCVCameraSource            app/live/webcam_camera.py
                  |
                  v
        runtime.ingest_frame(frame, timestamp)      <- same ingest path
                  |
   FrameIngestion -> FrameSampler -> RollingFrameBuffer
                  -> YOLO detection -> tracking -> events
                  -> ForensicEvidence -> PostgreSQL + MinIO (sha256) -> Qdrant -> VLM
``

* `LocalOpenCVCameraSource` implements the full `CameraSource` contract
  (`connect`/`disconnect`/`read_frame`/`start`/`stop`/`is_alive`/`health`).
* `WebcamCameraSource` (`name="webcam"`) reads `WEBCAM_*` settings;
  `UsbCameraSource` (`name="droidcam_usb"`) reads `DROIDCAM_*`. Both feed
  the identical pipeline, so detection, tracking, evidence and audit behaviour
  cannot diverge between transports.
* `connect()` reads one real frame before declaring the device open, because
  `cv2.VideoCapture(0)` can report `isOpened() == True` for a device that
  does not exist. A missing camera therefore returns HTTP 503 instead of a
  silent zero-frame session.
* Reconnects are bounded by `WEBCAM_MAX_RESTARTS` (default 3) — there is no
  infinite reconnect loop; the session ends with a health `error` plus an audit
  record.
* `GET /live/cameras/{id}/status` exposes `source_health`
  (`opened`/`alive`/`running`/`frames_read`/`dropped_frames`/
  `restarts`/`last_frame_at`/`error`) and the evidence counters
  (`evidence_captured`/`evidence_indexed`/`evidence_failed`).
* Verification: `backend/scripts/verify_webcam.py` (device level) and
  `backend/scripts/verify_live_webcam.py` (full chain). See `WEBCAM_SETUP.md`.
