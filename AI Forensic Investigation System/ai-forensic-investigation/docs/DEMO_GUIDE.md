# DEMO_GUIDE.md — Demo scenarios and walkthrough

Everything needed to present the AI Forensic Investigation System end to end.

## 1. Prerequisites (one-time)

1. Backend deps: `pip install -r backend/requirements.txt` (Python 3.11).
2. Frontend deps: `cd frontend && npm install`.
3. Start PostgreSQL and (optionally) Qdrant. The backend degrades gracefully if
   only PostgreSQL is up — Qdrant falls back to in-memory, storage to local FS.

## 2. Fresh start

```bash
cd backend
python scripts/reset_demo_database.py   # schema + Alembic + seed
python -m uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm run dev
```

Open http://localhost:3000.

## 3. Demo accounts

| Role | Email | Password |
|------|-------|----------|
| Admin (demo) | `demo.admin@forensics-demo.com` | `DemoAdmin123!` |
| Investigator (demo) | `demo.investigation@forensics-demo.com` | `demo-investigation-2026` |
| Reviewer (demo) | `reviewer.demo@forensics-demo.com` | `ReviewerDemo123!` |

## 4. Walkthroughs

### 4.1 Live demo with a demo video file (no hardware)

Use the live camera page. Create/use a camera, start a session with
`transport=file` and `video_path` pointing to a dataset video, e.g.

```
backend/data/demo_investigation/videos/demo_video_01_parking_cars.mp4
```

You will see frames flowing, YOLO detections (absolute pixel boxes), multi-object
tracks, VLM observations, and evidence records appear as they are captured and
indexed (status visible in the frontend / `GET /live/sessions`).

### 4.2 Live demo with a phone (WebRTC)

1. Both phone and backend on the same LAN.
2. Start an empty session; the frontend negotiates WebRTC over the signaling
   socket (SDP offer/answer, ICE trickle).
3. Phone app streams frames; the pipeline runs identically.

### 4.3 Live demo with a USB / DroidCam camera (Phase 9 transport)

1. Install DroidCam Desktop 4 + the camera driver (or plug in a UVC camera).
2. Start the camera with `transport=droidcam_usb` (device index 0 default,
   override with `DROIDCAM_DEVICE_INDEX` / `device_index`).
3. Session status exposes source health (`frames_read`, `alive`, `restarts`) via
   `/live/cameras/{id}/status`.

### 4.4 Investigation + forensic analysis

Use the investigations UI to run a controlled Phase 7 investigation, then
trigger the Phase 8 forensic analysis. Review the produced timeline, findings
and PDF report. Findings lift from real evidence ids — never invented.

### 4.5 Evidence integrity

```bash
cd backend
python scripts/verify_evidence_integrity.py        # ledger↔storage↔vector
python scripts/verify_demo_dataset.py              # files + benchmark + artifacts
python scripts/run_full_e2e.py --base-url http://127.0.0.1:8000 --reset-db
```

`run_full_e2e.py` skips unavailable stages and reports
`NOT TESTED - DEPENDENCY UNAVAILABLE` rather than guessing.

## 5. What to say when presenting

- Search instead of scrubbing: natural-language queries over video via video RAG
  + policy RAG.
- Live: real-time detection/tracking/VLM with an evidence trail; every piece of
  evidence is hashed, stored, indexed and verifiable.
- Investigation: bounded agent that stops at reviewable findings; forensic layer
  reconstructs a chronological, evidence-grounded timeline and flags
  contradictions, gaps and low-resolution limitations.
- Honesty: no facial recognition, no timestamp invention, honest backend
  reporting (`/health`), simulated LLM provider is labeled as simulation.

## 6. Demo dataset

`backend/data/demo_investigation/` contains the 6-video dataset (`demo_video_01…06`),
`cases.json`, `expected_events/`, `expected_observations/`, and the scripts
`seed_demo_investigation.py` / `seed_demo_videos.py`. The evaluation benchmark
lives at `data/evaluation/benchmark.jsonl` (11 scenarios), consumed by
`scripts/evaluate.py`.