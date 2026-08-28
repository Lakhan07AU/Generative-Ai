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
