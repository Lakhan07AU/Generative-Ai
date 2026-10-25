# AI Forensic Investigation System — Part 1 (Foundation & Video Pipeline)

An academic **GenAI surveillance investigation assistant** that lets security
personnel investigate CCTV footage using natural-language queries instead of
manually reviewing hours of video.

> **Part 1 scope:** Project foundation, authentication, database, MinIO storage,
> asynchronous video upload & processing pipeline (FFmpeg → scene detection →
> clip extraction → keyframes → YOLO detection → tracking), audit logging, and a
> Next.js frontend for upload and investigation.
>
> This is an **investigation-assistance prototype**, not an autonomous security
> system. Parts 2–4 (GenAI video RAG, investigation agent, policy RAG,
> verification, reporting) build on this foundation.

---

## 1. Safety & Design Rules

- **No facial recognition.** No name/biometric identification.
- **No identity claims** — only visual tracking IDs (e.g. `Person-001`).
- **No human-intent inference.**
- **Original evidence is immutable** (MinIO object lock on uploads).
- **Never invent timestamps.** All timestamps come from source video metadata.
- **No fake/mock AI results.** If a model is unavailable, the pipeline degrades
  gracefully (fewer segments / no detections) rather than fabricating output.

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, TypeScript, Tailwind CSS, shadcn/ui-style components |
| Backend | Python, FastAPI, Pydantic |
| Database | PostgreSQL 15 (SQLAlchemy 2.0 + Alembic) |
| Object storage | MinIO (S3-compatible) |
| Video | FFmpeg, OpenCV, PySceneDetect |
| Computer vision | Ultralytics YOLO + IoU/ByteTrack-style tracker |
| Deployment | Docker + Docker Compose |

---

## 3. Project Structure

```
ai-forensic-investigation/
├── docker-compose.yml
├── .env.example                 # copy to .env
├── pytest.ini
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic/                 # migrations
│   └── app/
│       ├── main.py              # FastAPI app + CORS + lifespan
│       ├── core/config.py       # settings
│       ├── api/                 # auth, cameras, videos, dashboard, media
│       ├── auth/                # security, deps (JWT, roles)
│       ├── database/            # session, models
│       ├── video/               # ffmpeg_utils, scene_detection, pipeline, processor
│       ├── vision/              # tracker.py (YOLO wrapper + IoU tracker)
│       ├── audio/               # (placeholder for Part 2 whisper)
│       ├── storage/service.py   # MinIO wrapper
│       ├── audit/service.py     # audit logging
│       └── schemas/             # Pydantic models
├── frontend/
│   ├── Dockerfile
│   ├── app/                     # /login /register /dashboard /videos /videos/[id]
│   ├── components/              # UI + protected shell + header
│   └── lib/                     # api.ts, auth-context.tsx, utils.ts
├── data/                        # local work dir (gitignored)
├── models/                      # YOLO weights (gitignored)
├── scripts/                     # helper scripts
└── tests/                       # pytest suite
```

---

## 4. Environment Variables

Copy `.env.example` to `.env` and fill values:

```env
POSTGRES_DB=forensics
POSTGRES_USER=forensics
POSTGRES_PASSWORD=forensics_password
DATABASE_URL=postgresql+psycopg2://forensics:forensics_password@postgres:5432/forensics

MINIO_ENDPOINT=minio:9000
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_VIDEOS=forensics-videos
MINIO_BUCKET_CLIPS=forensics-clips
MINIO_BUCKET_FRAMES=forensics-frames
MINIO_BUCKET_THUMBNAILS=forensics-thumbnails

SECRET_KEY=use_a_long_random_string
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=120

YOLO_MODEL=yolov8n.pt
SCENE_SENSITIVITY=30.0
MAX_CLIPS=50
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Generate a strong secret:
`python -c "import secrets; print(secrets.token_urlsafe(64))"`

Never commit real `.env` files.

---

## 5. Setup & Running (Docker)

Prerequisites: Docker + Docker Compose, Git.

```bash
cp .env.example .env          # then edit values
docker compose up -d --build  # build & start all services
```

Services:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000 (docs at /docs)
- MinIO console: http://localhost:9001 (minioadmin / minioadmin)
- PostgreSQL: localhost:5432

The backend runs `alembic upgrade head` automatically on container start and
creates the required MinIO buckets.

### Local (without Docker) backend

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate   |  Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
# ensure a PostgreSQL + MinIO are reachable (see .env), then:
alembic upgrade head
uvicorn app.main:app --reload
```

### Local frontend

```bash
cd frontend
npm install
npm run dev
```

---

## 6. Database Migrations

Migrations live in `backend/alembic/versions/`.

```bash
# inside the backend container/workdir:
alembic upgrade head     # apply
alembic downgrade -1     # revert last
# autogenerate a new migration after model changes:
alembic revision --autogenerate -m "description"
```

The container already runs `alembic upgrade head` at startup.

---

## 7. API Overview

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/auth/register` | Register user (role selectable) |
| POST | `/auth/login` | Login → JWT + user |
| POST | `/auth/logout` | Logout (stateless) |
| GET | `/auth/me` | Current user |
| POST | `/videos/upload` | Upload CCTV, create processing job |
| GET | `/videos` | List videos |
| GET | `/videos/{id}` | Video detail + clips + events |
| GET | `/videos/{id}/status` | Processing job status/progress |
| POST | `/videos/{id}/process` | (Re)start processing |
| GET | `/videos/{id}/clips` | Clips |
| GET | `/videos/{id}/detections` | Timestamped detections |
| GET | `/videos/{id}/events` | Events |
| GET | `/cameras` | List cameras |
| POST | `/cameras` | Create camera |
| GET | `/dashboard/stats` | Dashboard stats |
| GET | `/media/original/{video_id}` | Presigned original video URL |
| GET | `/media/clips/{clip_id}` | Presigned clip URL |
| GET | `/media/thumbnails/{clip_id}` | Presigned thumbnail URL |

---

## 8. Video Processing Pipeline

```
Upload → [UPLOADED] → [QUEUED] → [PROCESSING] → [READY | FAILED]
                    (background task)
METADATA → SCENE_DETECTION → CLIP_EXTRACTION → DETECTION → TRACKING → INDEX_READY
   FFmpeg      PySceneDetect       FFmpeg          YOLO        IoU tracker
```

- Original uploaded video is stored **immutably** in MinIO `forensics-videos`.
- Each clip stores `video_id`, `clip_id`, `camera_id`, `start_time`, `end_time`,
  `storage_path`, `thumbnail_path`.
- Detections store `label`, `bounding_box`, `frame_number`, `timestamp`,
  `detection_confidence`, `tracking_id`.
- Progress and current `stage` are persisted and exposed via the status endpoint.

---

## 9. Frontend Pages

- `/login`, `/register`
- `/dashboard` — totals (videos, jobs, completed, detections) + recent uploads
- `/videos` — upload form + video list with status (auto-refreshing)
- `/videos/[id]` — video player, metadata, processing progress, extracted clips,
  timestamped detections (click a detection to jump the player to that time),
  and detected events.

---

## 10. Running Tests

```bash
# From project root (backend venv must have test deps installed)
python -m pytest -q
```

> The suite is split so most tests run without external services (using a
> temporary SQLite DB). Tests that need FFmpeg and/or MinIO are automatically
> **skipped** when those services are not present. To run the full suite, ensure
> FFmpeg is on `PATH` and MinIO/Postgres are reachable (e.g. inside the backend
> container).

Covered: authentication, invalid role, JWT protection, camera CRUD, video upload
validation, MinIO dev/quality, database relationships, audit logging, IoU
tracker, metadata extraction, scene detection, clip timestamps, processing
failure handling.

---

## 11. Integration Gate (Part 1 completion criteria)

The following flow must work end to end:

```
Login → Upload CCTV → processing job created → background processing
→ FFmpeg → scene detection → clip extraction → YOLO → tracking
→ store results → open video dashboard → view timestamped detections
```

---

## 12. Docker commands

```bash
docker compose up -d                       # start all
docker compose up -d --build               # rebuild + start
docker compose up -d postgres minio        # infra only
docker compose logs -f backend             # backend logs
docker compose exec backend bash           # shell into backend
docker compose down                        # stop
docker compose down -v                     # stop + remove volumes (wipes data)
docker ps                                  # status
```

---

## 13. Known Issues & Notes

- **Python 3.14 on Windows host:** the pinned `requirements.txt` targets the
  Python 3.11 Docker image. Running the backend on a local Python 3.14 may need
  `pip install ultralytics opencv-python scenedetect` upgrades; the heavy CV
  packages (torch/ultralytics) can fail on Windows when the project path is very
  long (`WinError 206`). The Docker image uses a short `/app` path and avoids this.
- **GPU not required:** YOLO runs on CPU by default in this prototype; a GPU
  makes detection faster but is optional.
- **First backend build is large** (downloads PyTorch ~500 MB+) and takes minutes.
- **Scene detection** uses PySceneDetect; if unavailable it falls back to
  fixed-length segmentation so processing never silently stalls.
- **Detection capacity** depends on the environment — if `ultralytics` or the
  model weights cannot load, detections are skipped (no fabricated results).
- Uploads smaller than the max request size are fine; for very large files you
  may need to raise the reverse proxy/body limit in production.
- Original object immutability is implemented with MinIO **object locking** on
  the `videos` bucket (COMPLIANCE mode). Some MinIO/backend configurations may
  require the retention feature enabled on the bucket.
- `data/` and `models/*.pt` are gitignored; create them if missing.

---

## 14. Roadmap (Parts 2–4)

- **Part 2:** Video RAG (clip embeddings in Qdrant, natural-language search).
- **Part 3:** Investigation agent (langgraph tool calling), evidence verification.
- **Part 4:** Security policy RAG, timeline reasoning, automated incident report.

The modular backend (`video/`, `vision/`, `audio/`, `api/`, `storage/`,
`database/`) is designed so these layers integrate without rewriting Part 1.

---

## 15. Current Status (through Phase 9)

The prototype now spans nine phases of investigation-assistance capability plus
production hardening. Reports live beside this README:

| Phase | Focus | Report |
|-------|-------|--------|
| 1 | Foundation, upload pipeline, auth, audit | `PHASE1_REPORT.md` |
| 2 | Video RAG, clip embeddings (Qdrant), policy RAG | `PHASE2_REPORT.md` |
| 3 | Real-time live camera + detection/tracking | `PHASE3_REPORT.md` |
| 4 | Real-time VLM observations (grounded) | `PHASE4_REPORT.md` |
| 5 | Live evidence capture + durable indexing | `PHASE5_REPORT.md` |
| 6 | Demo investigation dataset + retrieval bounds | `PHASE6_REPORT.md` |
| 7 | Controlled investigation agent | `PHASE7_REPORT.md` |
| 8 | Forensic timeline / verification / reporting | `PHASE8_REPORT.md` |
| 9 | Production hardening audit + fixes | `PHASE9_SYSTEM_AUDIT.md`, `PHASE9_REPORT.md` |

### Phase 9 hardening at a glance

- **Honest backends**: `/health` + `/metrics` report which vector/object stores
  are actually live (Qdrant vs in-memory, MinIO vs local FS).
- **Credential protection**: sliding-window login rate limit
  (`LOGIN_RATE_LIMIT_*`), startup warning on known dev `SECRET_KEY`.
- **Clean-start tooling**: `backend/scripts/reset_demo_database.py` (schema
  reset + migrations + seed), `backup_database.py` (pg_dump/SQLite).
- **Verifiers**: `verify_evidence_integrity.py` (sha256/orphans/index sync),
  `verify_demo_dataset.py`, `run_full_e2e.py` (dependency-gated,
  `NOT TESTED - DEPENDENCY UNAVAILABLE` semantics).
- **New live transport**: `droidcam_usb` (USB/DroidCam camera capture) via a
  proper `CameraSource` abstraction (`app/live/source.py`, `app/live/usb_camera.py`).
- **Audit trail + ops visibility**: `GET /audit/logs` + `GET /audit/actions`
  (ADMIN) surfaced through a new audit UI screen.
- **Full test suite is green**: 405 tests across 34 modules pass; the 11-stage
  end-to-end verifier passes all stages (db, cleaning, health, login, live file
  session, VLM observation, evidence index/integrity, investigation agent run,
  forensic analysis); demo dataset verifier 31 PASS / 0 FAIL / 0 WARN; evidence
  integrity CLEAN (see `PHASE9_REPORT.md` and results JSON under
  `backend/data/demo_investigation/results/`).

Ongoing operations, architecture, demo, troubleshooting and security notes are
in the `docs/` folder:

- `docs/OPERATIONS.md`
- `docs/ARCHITECTURE.md`
- `docs/DEMO_GUIDE.md`
- `docs/TROUBLESHOOTING.md`
- `docs/SECURITY.md`

---

## 16. Laptop Webcam Transport + Final Verification (2026-09-27)

A real local-camera transport (`webcam`) is now available in the Live Console
alongside `webrtc` / `simulation` / `file` / `droidcam_usb`. It shares a
single OpenCV capture implementation (`LocalOpenCVCameraSource`) and the same
ingest, detection, tracking, evidence and audit path — no second pipeline.

| Variable | Default | Meaning |
|---|---|---|
| `WEBCAM_DEVICE_INDEX` | 0 | OpenCV capture index (0 is not guaranteed to exist — probe it) |
| `WEBCAM_FPS` | 10 | Requested capture rate |
| `WEBCAM_WIDTH` / `WEBCAM_HEIGHT` | 640 / 480 | Requested capture size |
| `WEBCAM_STALE_SECONDS` | 5.0 | No frame for this long → `alive=false` |
| `WEBCAM_MAX_RESTARTS` | 3 | Bounded reconnects (never infinite) |

Usage, probing and the Docker caveat are documented in `WEBCAM_SETUP.md`.

### PHYSICAL LIVE CAMERA VERIFICATION

| Check | Result |
|---|---|
| Camera detected (device 0-3) | **NOT TESTED** — `/dev/video*` absent in the container; `verify_webcam.py --probe` → `RESULT: NO DEVICE` |
| Frame capture / live ingestion | NOT TESTED (depends on the above) |
| YOLO / tracking / events / evidence | VERIFIED on real frames from the demo **file** transport (not from a camera) |
| PostgreSQL / MinIO / Qdrant | **PASS** — real services, alembic head `0008_phase8_forensics`, Qdrant dims 384, no in-memory fallback |
| VLM | **NOT TESTED** — `REAL VLM PROVIDER NOT TESTED` (no credentials configured) |
| RAG / LangGraph / timeline / finding verification / human review / PDF report | **PASS** — Phases 6/7/8 green; PDF now renders via ReportLab |
| Test suite | **PASS** — 419 tests, 0 failures (405 + 14 new webcam tests) |
| `npm run build` | **PASS** |

Overall: `FINAL STATUS: NOT READY` — the single blocker is that the physical
laptop webcam is not reachable from the verification environment, so the live
camera chain has no evidence of success. Full detail and the exact reproduction
steps: `FINAL_SYSTEM_REPORT.md`.

### Verifier entry points

| Script | Scope |
|---|---|
| `backend/scripts/verify_phase5.py` | evidence model, PostgreSQL, alembic head, MinIO frames/reports, real Qdrant, evidence integrity |
| `backend/scripts/verify_phase6.py` | video RAG against real evidence + live API |
| `backend/scripts/verify_phase7.py` | LangGraph investigation agent graph |
| `backend/scripts/verify_phase8.py` | forensic analysis, timeline, verification, report + PDF |
| `backend/scripts/verify_webcam.py` | real capture device (probe / capture test) |
| `backend/scripts/verify_live_webcam.py` | webcam → session → ingest → YOLO → tracking → events → evidence → PG → MinIO → Qdrant → VLM |
| `backend/scripts/verify_final_system.py` | everything, with the final status matrix |

Run `python backend/scripts/verify_final_system.py` for the full matrix. A
skipped or unrunnable section is reported as `NOT TESTED` and forces
`FINAL STATUS: NOT READY`.
