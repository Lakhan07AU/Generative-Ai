# PROGRESS REPORT — 1

## AI Forensic Investigation System
### A GenAI-Powered Natural-Language Investigation Assistant for CCTV Footage

| Field | Detail |
|---|---|
| **Project title** | AI Forensic Investigation System |
| **Project type** | Academic capstone — Generative AI application development |
| **Report** | Progress Report 1 (first internal review) |
| **Reporting period** | Phase 0 – Phase 9 (2026-09-11 → 2026-09-27) |
| **Date of submission** | 2026-09-28 |
| **Team members** | _[Name, Roll No.]_ · _[Name, Roll No.]_ · _[Name, Roll No.]_ |
| **Project guide** | _[Guide Name, Designation]_ |
| **Department** | _[Department, Institution]_ |
| **Repository** | `AI Forensic Investigation System/ai-forensic-investigation` |
| **Overall status** | **Core system COMPLETE and VERIFIED — 1 open blocker (physical camera chain NOT TESTED)** |

> **Note on honesty of this report.** Every status in this document is either
> **PASS** (executed against real services and recorded with evidence) or
> **NOT TESTED** (could not be executed in the verification environment).
> No result in this report is simulated, estimated, or projected.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement and Motivation](#2-problem-statement-and-motivation)
3. [Objectives](#3-objectives)
4. [Scope and Non-Goals](#4-scope-and-non-goals)
5. [Technology Survey](#5-technology-survey)
6. [System Architecture as Built](#6-system-architecture-as-built)
7. [Work Completed — Phase by Phase](#7-work-completed--phase-by-phase)
8. [Verification and Evaluation Results](#8-verification-and-evaluation-results)
9. [Demo Dataset and Demonstration](#9-demo-dataset-and-demonstration)
10. [Defects Found and Resolved](#10-defects-found-and-resolved)
11. [Challenges Faced and Mitigation](#11-challenges-faced-and-mitigation)
12. [Ethical and Safety Compliance](#12-ethical-and-safety-compliance)
13. [Honest Limitations and Open Blockers](#13-honest-limitations-and-open-blockers)
14. [Plan for the Next Reporting Cycle](#14-plan-for-the-next-reporting-cycle)
15. [Conclusion](#15-conclusion)
16. [Appendix A — Artifact Index](#appendix-a--artifact-index)
17. [Appendix B — Reproduction Commands](#appendix-b--reproduction-commands)

---

## 1. Executive Summary

Security personnel investigating an incident must review hours of CCTV footage
manually. This is slow, semantically blind (they can only search by timestamp or
camera, not by meaning), and highly prone to missed evidence. Traditional
surveillance analytics solve only part of this: they detect pre-defined objects
but cannot reason temporally or semantically across a long recording.

This project builds an **investigation-assistance platform** that converts raw
surveillance footage into a searchable, evidence-grounded knowledge store, and
lets an investigator ask questions in natural language:

> *"When did the person enter the restricted area?"*
> *"Was this entry a violation of security policy?"*
> *"Generate the incident report with supporting evidence."*

**Progress to date.** A working, containerised, test-verified system has been
delivered across ten increments (foundation + Phases 1–9). The complete chain
works end to end against real infrastructure:

```
Live / uploaded CCTV
   → frame ingestion → YOLOv8 detection → IoU multi-object tracking
   → event generation → VLM semantic observation
   → evidence capture (JPEG + SHA-256) → MinIO + PostgreSQL
   → embeddings → Qdrant → hybrid Video RAG search
   → LangGraph investigation agent (plan → retrieve → verify → synthesise)
   → forensic timeline + finding verification + human review
   → 15-section PDF incident report
```

**Measured state at the close of this period**

| Indicator | Value |
|---|---|
| Backend Python modules | 139 files under `backend/app/` |
| Automated tests | **430 passing, 0 failures, 0 errors** |
| Test modules | 42 files under `tests/` |
| Alembic migrations | 8 (`0001_initial` → `0008_phase8_forensics`, head applied) |
| Frontend routes | 20 (Next.js 14.2.5 production build clean) |
| End-to-end verifier | 11 stages, 0 failed |
| Phase verifiers | Phase 5 **PASS**, Phase 6 **PASS (103 checks)**, Phase 7 **PASS (38 checks)**, Phase 8 **PASS (46 checks)** |
| Demo dataset verifier | **196 checks, 0 failures**, 7/7 sections |
| Demo investigation evidence | 113 artefacts indexed, 0 failed |
| Real infrastructure used | PostgreSQL 15.19, MinIO (S3), Qdrant v1.9.4 (384-dim), Docker Compose |
| Inference device | **CPU only** (`torch.cuda.is_available() == False`) |
| Detection throughput | ~138 ms/frame (live sim), ~212 ms/frame (demo video), `yolov8n` @ 640px |
| Search latency | 62–146 ms (RAG), 182–206 ms (agent run) |
| Open blockers | **1** — physical camera chain NOT TESTED (§13) |

---

## 2. Problem Statement and Motivation

### 2.1 The problem

| Pain point | Consequence |
|---|---|
| Hundreds of hours of footage reviewed manually | Delayed incident response |
| No semantic search — only timestamp/camera filtering | Investigators must already know what they are looking for |
| Long, unattended review | Missed evidence, inconsistent recall |
| Manual report compilation | Slow, and findings are not systematically traceable to source evidence |
| LLM-based analysis of video | Hallucinated timestamps, fabricated identities, unverifiable claims |

### 2.2 Why a GenAI project

Traditional CV gives *detection*. It does not give *interpretation*. The
investigative questions a security officer actually asks are semantic and
temporal ("who approached the equipment after 10:42?", "does that match SOP-4?").
Answering them requires retrieval over long-form video plus grounded reasoning —
which is exactly what RAG, multimodal models and agentic workflows provide.

### 2.3 Proposed solution

Ingest surveillance video, convert it into a multimodal knowledge base, and
expose it through an agent that answers investigative questions **with explicit
evidence references and explicit uncertainty**.

---

## 3. Objectives

### 3.1 Primary objective

Build and verify a working prototype that lets a security investigator upload
CCTV footage and, using natural-language queries, determine *what happened, when
it happened, what evidence supports it, whether it violates policy, and produce
a structured incident report.*

### 3.2 Measurable objectives and achievement status

| # | Objective | Metric | Target | Achieved |
|---|---|---|---|---|
| O1 | End-to-end ingest → report pipeline works | E2E verifier stages | 11/11 | **11/11 PASS** |
| O2 | Automated test coverage | pytest | 0 failures | **430 passed, 0 failed** |
| O3 | Natural-language video search | Demo RAG verifier | all cases | **103 checks PASS** |
| O4 | Bounded agentic investigation | Agent verifier | all cases | **38 checks PASS** |
| O5 | Verified, traceable findings | Forensic verifier | all cases | **46 checks PASS** |
| O6 | PDF incident report | Real PDF via ReportLab | renders + stores | **PASS** (~30 ms render) |
| O7 | Grounded demo dataset | Demo verifier | 7 sections | **196 checks, 0 failures** |
| O8 | Frontend production build | `npm run build` | clean | **PASS (20 routes)** |
| O9 | Real infrastructure (no mocks) | PG/MinIO/Qdrant live | all live | **PASS**, no in-memory fallback |
| O10 | Physical camera end-to-end | webcam → report | PASS | **NOT TESTED** — blocker |

---

## 4. Scope and Non-Goals

### 4.1 In scope

Video upload and asynchronous processing · scene detection and clip
segmentation · object detection and multi-object tracking · real-time live camera
ingestion (WebRTC phone, laptop webcam, USB/DroidCam, file, simulation) ·
multimodal VLM observation · evidence capture with cryptographic hashing ·
Video RAG with hybrid retrieval · Security Policy RAG · bounded LangGraph
investigation agent · forensic timeline reconstruction · evidence verification
with human review · PDF incident report generation · RBAC, audit trail and
operational endpoints.

### 4.2 Explicitly out of scope (deliberate design decisions)

- **No facial recognition and no biometric identification.**
- **No name or identity attribution** — only visual tracking IDs
  (`Person-000001`).
- **No intent inference** (the system never claims what a person *meant*).
- **No autonomous security decisions** — human review is mandatory before any
  report is finalised.
- No custom LLM training, no Kubernetes, no enterprise IAM, no mobile app.

These are not deferrals; they are the project's core safety contract and are
enforced in code (see §12).

---

## 5. Technology Survey

The stack was selected against four criteria: real availability of an
open-source implementation, CPU-viability, licence compatibility for an academic
deliverable, and fit with the evidence-traceability requirement.

| Layer | Technology | Version | Rationale |
|---|---|---|---|
| Frontend | Next.js + React + TypeScript + Tailwind | 14.2.5 | App-router SPA; typed API client; production build gate |
| Backend API | FastAPI + Pydantic v2 | — | Async, typed, auto OpenAPI docs for API-first design |
| ORM / migrations | SQLAlchemy 2.0 + Alembic | — | Versioned, reversible schema history (8 revisions) |
| Relational store | PostgreSQL | 15.19 | Authoritative record of evidence, events, runs, reviews |
| Object storage | MinIO | RELEASE.2025-09-07 | S3-compatible; object lock for evidence immutability |
| Vector store | Qdrant | v1.9.4 (384-dim) | Metadata-filtered hybrid retrieval |
| Video decode | FFmpeg / OpenCV | OpenCV 4.10.0.84 | Containerised pipeline |
| Scene detection | PySceneDetect | 0.6.4 | Content-aware clip segmentation |
| Object detection | Ultralytics YOLOv8n | 8.2.57 | 80 COCO classes, CPU-viable, well documented |
| Tracking | Custom IoU multi-object tracker | — | Dependency-free; label-aware greedy IoU assignment |
| Real-time transport | aiortc + MJPEG + OpenCV capture | aiortc 1.15.0 | Phone WebRTC, laptop webcam, USB camera, file replay |
| Agent orchestration | LangGraph | 1.2.11 | Explicit bounded `StateGraph` with tool calling |
| VLM abstraction | OpenAI-compatible multimodal endpoint | — | Provider-agnostic; `simulation` mode for offline runs |
| Report rendering | ReportLab | 4.2.5 | Deterministic PDF output |
| ML runtime | PyTorch | 2.14.0+cu130 | Inference on CPU (`cuda` unavailable) |
| Testing | pytest | 8.2.2 | 430 automated tests |
| Deployment | Docker + Docker Compose | — | Reproducible 5-service deployment |

---

## 6. System Architecture as Built

### 6.1 Layer diagram

```text
┌───────────────────────────────────────────────────────────────────┐
│  Next.js 14 Frontend  (/login /dashboard /videos /live /search    │
│  /evidence /investigations /runs/[id] /reports /policies /demo    │
│  /audit /settings)                                                 │
└───────────────────────────────┬───────────────────────────────────┘
                                │  REST + WebSocket + MJPEG
┌───────────────────────────────▼───────────────────────────────────┐
│  FastAPI Application                                              │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────────────┐ │
│  │  auth /  │  video/  │  live/   │ evidence/│ investigation/   │ │
│  │   RBAC   │ pipeline │ runtime  │ capture  │  query+retrieval │ │
│  ├──────────┼──────────┼──────────┼──────────┼──────────────────┤ │
│  │detection/│tracking/│  vlm/    │investigator/ (LangGraph)    │ │
│  │  YOLO    │  IoU     │ observe  │                               │ │
│  ├──────────┼──────────┼──────────┼──────────┬──────────────────┤ │
│  │  forensic/ (timeline, verification, gaps, report)  │  rag/    │ │
│  └──────────┴──────────┴──────────┴──────────┴──────────────────┘ │
└───────┬──────────────────┬──────────────────┬─────────────────────┘
        │                  │                  │
┌───────▼────────┐ ┌───────▼────────┐ ┌───────▼────────┐
│  PostgreSQL 15 │ │  MinIO (S3)    │ │  Qdrant 384-d  │
│  authoritative │ │  immutable     │ │  vector index  │
│  records       │ │  evidence      │ │  + metadata    │
└────────────────┘ └────────────────┘ └────────────────┘
```

### 6.2 Data flow for one investigative question

```text
Investigator question
      │
      ▼
LangGraph planner  ──► bounded tool budget (8 steps / 14 calls / 120 s)
      │
      ├─► hybrid retrieval:  Qdrant semantic  +  PostgreSQL authoritative
      │        (temporal / object-class / track-id / event-type filters)
      ├─► VLM statements admitted ONLY when tagged [OBSERVED]
      ├─► conflict detection  ──► contradictions reported, never resolved
      ▼
Forensic pipeline (7 deterministic read-only stages)
   load → correlate → timeline → verify → contradictions → gaps → sequencing
      │
      ▼
Findings (FINDING-xx) with weighted support
   direct_visual .25 | event_match .20 | track_match .20 | timestamp_match .15
   camera_match .05 | vlm_support .10 | independent_sources .10
      │
      ▼
Human review (ACCEPTED / REJECTED / MARKED_UNCERTAIN / REQUESTED_MORE_EVIDENCE)
   with an immutable finding snapshot
      │
      ▼
15-section incident report → ReportLab PDF → MinIO (versioned)
```

### 6.3 Database schema (8 migrations, head = `0008_phase8_forensics`)

Core entities: `users` (RBAC), `cameras` (+`is_live`, `stream_status`),
`camera_sessions`, `videos`, `clips`, `detections`, `events`,
`processing_jobs`, `audit_logs`, `policies` + `policy_chunks`,
`forensic_evidence` (SHA-256, provenance, index status),
`vlm_observation_records`, `investigations`, `investigation_runs`,
`forensic_analyses`, `forensic_timeline_events`, `finding_reviews`,
`forensic_reports`.

---

## 7. Work Completed — Phase by Phase

### 7.0 Foundation (Part 1) — project skeleton and offline pipeline

Delivered: Next.js 14 frontend, FastAPI backend, PostgreSQL schema and Alembic
chain, MinIO storage with **object lock (COMPLIANCE mode) on the original-video
bucket**, JWT authentication with three roles (`ADMIN`,
`SECURITY_OFFICER`, `INVESTIGATOR`, `REVIEWER`), audit logging, and the
asynchronous offline video pipeline:

```
Upload → [UPLOADED] → [QUEUED] → [PROCESSING] → [READY | FAILED]
   METADATA → SCENE_DETECTION → CLIP_EXTRACTION → DETECTION → TRACKING → INDEX_READY
     FFmpeg      PySceneDetect         FFmpeg          YOLO        IoU tracker
```

Key modules: `app/video/{ffmpeg_utils,scene_detection,pipeline,processor}.py`,
`app/vision/tracker.py`, `app/storage/service.py`, `app/audit/service.py`.
Status and stage are persisted and exposed via `GET /videos/{id}/status`.
**Integration gate met**: login → upload → background processing → detections →
timestamped dashboard with click-to-seek.

### 7.1 Phase 1 — Real-time mobile camera ingestion (WebRTC)

- `aiortc`-based receive-only peer connection; browser is the sender.
- Bounded rolling frame buffer (15 s window / 150 frames, concurrency-safe).
- Frame sampler decimating the source stream to a target rate (default 5 FPS).
- Session state machine `CONNECTING → LIVE → STOPPING → COMPLETED /
  DISCONNECTED / ERROR`, one active session per camera (409 otherwise).
- Signalling WS and status WS kept **separate** from frame processing.
- Migration `0005_phase1_live`; 48 phase tests.
- **Not tested:** real-device WebRTC round trip.

### 7.2 Phase 2 — Real-time YOLO detection layer

- `app/detection/` (6 modules): Ultralytics wrapper with an `RLock`-serialised
  shared engine, EMA FPS/latency metrics, per-session daemon worker with a
  bounded newest-wins queue (size 8), Pydantic detection schemas.
- Dedicated detections WebSocket; DPR-aware bounding-box overlay on the console.
- `yolov8n.pt`, 80 COCO classes, imgsz 640, conf 0.30, CPU device.
- Measured: model load 31–47 ms, warm-up ~4.0 s, **~138.5 ms/frame** on the live
  simulation feed.
- Fixed a `torch.load(weights_only=False)` incompatibility so Ultralytics 8.2.x
  legacy checkpoints load on Torch 2.6+.

### 7.3 Phase 3 — Multi-object tracking and event generation

- `app/tracking/` (7 modules): dependency-free label-aware greedy **IoU**
  multi-object tracker; track states `NEW / ACTIVE / LOST / REMOVED`; motion
  classification (stationary tolerance 4 px, 20 s / 100 frame minimum);
  event detector emitting `object_entered`, `object_exited`, `object_stopped`.
- Configurable `TRACKING_IOU_THRESHOLD=0.3`, `TRACKING_MAX_MISSING=30`,
  `TRACKING_MAX_TRACKS=200`; 22 new tests.
- **Two real production bugs caught and fixed** at this stage: a
  Pydantic-vs-dict contract mismatch that would have silently disabled tracking
  in production, and a cumulative-vs-live counter error.

### 7.4 Phase 4 — Multimodal VLM observation layer

- `app/vlm/` (9 modules): frame selection, JPEG pre-encode/downscale, context
  assembly, rate limiting, trigger policy, worker, per-session lifecycle.
- **Grounded statement typing**: every observation is classed
  `OBSERVED` / `INFERRED` / `UNKNOWN`, with a forbidden-substring guardrail
  lexicon blocking identity, name and intent claims.
- Provider abstraction extended additively (`vision_observe_frames`) with real
  and simulated backends; `POST /live/cameras/{id}/vlm/analyze` +
  `vlm_observation` WebSocket.
- Separate offline harness `app/validation/vlm_check.py` scores fact coverage,
  fabrication and prohibited themes, plus a curated 14-item internet test
  dataset (≈18 MB, Pexels + Blender Foundation, correctly licensed) with magic-
  byte and SHA-256 validation.
- 35 new tests. **Not tested:** a real VLM provider run (no credentials
  available in the environment).

### 7.5 Phase 5 — Forensic evidence capture, storage and vector indexing

- `app/evidence/` (4 modules): deterministic evidence paths
  (`live/{camera}/{session}/{date}/{id}/original.jpg`), SHA-256 content
  identity, de-duplication on `(sha256, camera_id, session_id)`, and an index
  queue with a `PENDING → INDEXING → INDEXED / FAILED` state machine including
  retry, backoff and truncated error capture.
- RBAC evidence API: list (filterable), fetch with `X-Evidence-Sha256` response
  header, content fetch, re-index, and vector search.
- Migration `0006_phase5_evidence`; 46 new tests.
- Verified against **real** PostgreSQL, MinIO and Qdrant (384-dim, no fallback).

### 7.6 Phase 6 — Grounded investigation search (Video RAG)

- `app/investigation/`: deterministic query parser (no LLM in the parse path),
  hybrid retrieval (Qdrant semantic + PostgreSQL authoritative), transparent
  composite reranking with per-event de-duplication, and answer assembly.
- Query intents `PRESENCE / COUNT / WHAT_HAPPENED / TRACK_HISTORY / OTHER`;
  entity aliases with plural tolerance; event hints
  (`entered → object_entered`); track-ID pattern support.
- **Three abstention guardrails** — the system returns
  `UNKNOWN — INSUFFICIENT EVIDENCE` when the intent is unanswerable, when no
  evidence exists, or when all candidates fall below
  `RAG_VERIFICATION_THRESHOLD=0.55`. VLM statements are cited only when the
  stored content carries `[OBSERVED]`.
- Verified: **103 checks, 0 failures**; measured latencies 62–146 ms.

### 7.7 Phase 7 — Bounded LangGraph investigation agent

- `app/investigator/` (9 modules): `StateGraph` with
  `build_plan → analyze → verify → synthesize → build_timeline` plus an
  unanswerable short-circuit.
- **Hard budget:** max 8 steps, 14 tool calls, 40 evidence items, 120 s wall
  clock — the agent cannot loop indefinitely.
- Run state machine `CREATED → PLANNING → RETRIEVING → ANALYZING → VERIFYING →
  BUILDING_TIMELINE → READY_FOR_REVIEW → COMPLETED` with terminal
  `FAILED / CANCELLED`; illegal transitions raise.
- **Prompt-injection defence:** evidence text is sanitised and only literal
  `[OBSERVED]` statements are citable, so a hostile string inside evidence
  cannot become an instruction.
- `conflicts.py` **reports contradictions and never resolves them**
  (e.g. `object_entered` at t=36120.0 vs `object_exited` at t=36122.0).
- Migration `0007_phase7_investigator`; 38/38 verifier checks; 182–206 ms.

### 7.8 Phase 8 — Forensic verification, timeline and reporting

- `app/forensic/`: 7 deterministic, read-only stages — load, correlation,
  timeline (`TL-xx`), verification (`FINDING-xx`), contradiction, gaps,
  sequencing, multi-camera.
- **Conservative by construction:** sequencing relationships are all
  `causal: false`; multi-camera output is only `POSSIBLE_CORRELATION` or
  `UNKNOWN` and **never** `SAME_OBJECT`; quality flags mark
  `track_only_without_visual`, `vlm_inferred_not_observed`,
  `low_resolution_frame_only`.
- **Human-in-the-loop review** with an immutable `finding_snapshot` and four
  reviewer actions.
- 15-section report rendered to a **real PDF** via ReportLab and stored
  versioned in MinIO. Migration `0008_phase8_forensics`.
- 19/19 unit tests; **46/46** verifier checks across 5 scenarios (COMPLETE,
  TEMPORAL, UNKNOWN, CONFLICT, EVIDENCE-GAP).

### 7.9 Phase 9 — Production hardening, audit and delivery readiness

- Sliding-window **login rate limiting** (5 attempts / 60 s per `IP + email`,
  HTTP 429 with `Retry-After`, bucket reset on success).
- Honest operational endpoints: `GET /health` reports the **actual** backends in
  use (Qdrant vs in-memory, MinIO vs local FS); `GET /metrics` exposes
  Prometheus text.
- Admin audit API (`GET /audit/logs`, `GET /audit/actions`) plus a new audit UI
  screen.
- Clean-start and backup tooling: `reset_demo_database.py`,
  `backup_database.py`.
- Verifiers: `verify_evidence_integrity.py`, `verify_demo_dataset.py`,
  `run_full_e2e.py` with explicit `NOT TESTED — DEPENDENCY UNAVAILABLE`
  semantics.
- Production-shaped Docker Compose (no dev bind mounts, container healthchecks,
  `alembic upgrade head` on boot, multi-stage non-root frontend image).
- Documentation set: `docs/{ARCHITECTURE,OPERATIONS,DEMO_GUIDE,TROUBLESHOOTING,
  SECURITY}.md`.
- **11-stage end-to-end verification, 0 failed.**

### 7.10 Laptop webcam transport and final verification

- One capture implementation, two transport names:
  `LocalOpenCVCameraSource` in `app/live/webcam_camera.py`, with
  `UsbCameraSource` reduced to a 4-line subclass supplying only its name and
  settings prefix — **no second pipeline, no duplicated detection or tracking**.
- Five transports now available in the Live Console: *Phone WebRTC (real)*,
  *Laptop Webcam (real)*, *USB / DroidCam (real)*, *Simulation (synthetic)*,
  *Demo Video (not evidence)*.
- Hardening: `connect()` reads a real frame before reporting `opened=true`
  (a non-existent device otherwise reports healthy), reconnects bounded by
  `WEBCAM_MAX_RESTARTS=3`, staleness detection at 5 s.
- **MJPEG preview stream** (`GET /live/cameras/{id}/stream.mjpg`) publishing
  exactly the frames that enter the pipeline, so backend-owned cameras render
  instead of showing black; encoding is skipped entirely when nobody is
  watching, so WebRTC cost is unchanged.
- **Overlay letterboxing fix** — bounding boxes were being stretched onto the
  black pillar bars of a 4:3 camera; the overlay now computes the letterboxed
  content rectangle from real frame dimensions.
- Live status now reports the **actual** YOLO model, torch device and mean
  inference latency, never an assumed CUDA device.

---

## 8. Verification and Evaluation Results

### 8.1 Verification philosophy

Three independent layers are used, so that a green result means something:

1. **Unit / integration tests** (`pytest`) — fast, no external services, run on
   every increment.
2. **Phase verifiers** (`verify_phase5..8.py`, `verify_video_rag_demo.py`,
   `verify_investigator_agent.py`, `verify_forensic_reporting.py`) — executed
   against the **live** API, PostgreSQL, MinIO and Qdrant.
3. **End-to-end verifiers** (`run_full_e2e.py`, `verify_final_system.py`,
   `verify_live_webcam.py`) — the complete chain, with dependency-gated
   `NOT TESTED` semantics so an unrunnable check can never be reported as a pass.

### 8.2 Final verification matrix

| Component | Status | Evidence |
|---|---|---|
| Phase 5 — evidence / storage | **PASS** | PostgreSQL 15.19, 10/10 tables, alembic head `0008`; MinIO PUT/GET/EXISTS + SHA-256 match, missing-object raises, corrupt bytes detected, duplicate PUT idempotent; real Qdrant insert/search/metadata-filter/negative-filter/delete, 384-dim |
| Phase 6 — Video RAG | **PASS** | 103 checks, 0 failures against the live API |
| Phase 7 — LangGraph agent | **PASS** | full graph, evidence-scoped retrieval, UNKNOWN abstention, review state machine |
| Phase 8 — forensic analysis | **PASS** | 46 checks; timeline, verification, gaps, contradiction; real PDF via ReportLab in MinIO |
| Test suite | **PASS** | 430 tests, 0 failures, 0 errors |
| Frontend build | **PASS** | `npm run build` clean, 20 routes |
| End-to-end (11 stages) | **PASS** | 0 failed |
| Evidence integrity | **CLEAN** | DB ↔ Qdrant ↔ MinIO consistent, 0 orphans |
| Demo dataset | **PASS** | 196 checks, 0 failures, 7/7 sections |
| **Physical webcam capture** | **NOT TESTED** | no `/dev/video*` in the container; probe → `RESULT: NO DEVICE` |
| **Webcam → report with live frames** | **NOT TESTED** | depends on the above |
| **Real VLM provider** | **NOT TESTED** | no provider credentials configured |
| GPU inference | **N/A** | `torch.cuda.is_available() == False`; all inference on CPU |

### 8.3 Measured system metrics

| Metric | Value | Context |
|---|---|---|
| YOLO inference (live, simulation) | ~138.5 ms/frame avg | CPU, 640px, conf 0.30 |
| YOLO inference (demo video) | ~212 ms/frame avg | 585 detection frames, 349 detections |
| YOLO model load | 31–47 ms (warm), ~4.0 s (first inference) | cached engine |
| RAG search latency | 62–146 ms | top-k 8, hybrid |
| Agent run latency | 182–206 ms | bounded 8-step graph |
| Forensic pipeline | 21.7–43.5 ms endpoint | 5 scenarios |
| PDF report render | ~30 ms | incl. MinIO write |
| Live ingest (demo run) | 641 received / 641 sampled / 585 detected | 4 VLM observations, 4/4 evidence indexed |
| Login rate limit | 5 attempts / 60 s per `IP + email` | HTTP 429 + `Retry-After` |

### 8.4 Evaluation framework status

The PRD defines Recall@5/@10, Precision@5, MRR, timestamp error, temporal IoU,
context relevance/recall, answer faithfulness, factual accuracy, hallucination
rate and latency. **Honest status:** the retrieval and latency metrics are
exercised by the phase verifiers, and faithfulness/abstention are enforced and
tested structurally, but the **full labelled benchmark
(`data/evaluation/benchmark.jsonl`) is still to be authored**. Until it exists,
no published accuracy figure is claimed for this system.

---

## 9. Demo Dataset and Demonstration

### 9.1 Dataset

Ten CC-licensed videos with per-video scenarios, all processed with real YOLO
detections:

| ID | Scenario | Duration | Resolution | Detections / Events | Licence |
|---|---|---|---|---|---|
| DVS-001 | Vehicle detection (parking lane) | 30.2 s | 768×432 | 32 / 0 | CC BY 4.0 |
| DVS-002 | Multi-object tracking (street) | 53.9 s | 768×432 | 66 / 6 | CC BY 4.0 |
| DVS-003 | Crowd, complex scene (retail) | 65.4 s | 720×404 | 2116 / 13 | CC BY 4.0 |
| DVS-004 | Person detection (public plaza) | 49.7 s | 768×432 | 78 / 8 | CC BY 4.0 |
| DVS-005 | Prolonged presence (classroom) | 32.8 s | 1920×1080 | 1175 / 7 | CC BY 4.0 |
| DVS-006 | VLM scene understanding (cartoon) | 10.0 s | 640×360 | 7 / 0 | CC BY 3.0 |
| DVS-007 | Object entry/exit (corridor) | 139.4 s | 768×432 | 360 / 26 | CC BY 4.0 |
| DVS-008 | Object stopping (industrial) | 75.9 s | 1920×1080 | 145 / 15 | CC BY 4.0 |
| DVS-009 | Object movement (corridor) | 61.0 s | 768×432 | 89 / 9 | CC BY 4.0 |
| DVS-010 | Temporal investigation (walk + pause) | 90.9 s | 768×432 | 195 / 14 | CC BY 4.0 |

Plus 18 keyframes, 10 thumbnails, **2 negative fixtures**
(`not_a_video.mp4`, `empty_static_scene.mp4`), 12 scenarios (`SCN-01..12`) with
expected observations and expected events, and 10 investigation cases
(`CASE-DEMO-001..010`).

DVS-006 is deliberately a **negative** case: an animated cartoon yields
detections but **zero events**, demonstrating that the system does not
manufacture findings where none exist.

### 9.2 Demonstration flow (≈7 minutes, UI only)

1. Log in as the demo investigation user → dashboard.
2. Live Console → start a camera (simulation / demo video) → watch detections,
   tracks and events stream in.
3. Open the Forensic Evidence panel → inspect a record, its SHA-256 and its
   indexed state.
4. Search page → ask *"find when a person entered the area"* → retrieve clips
   with timestamps and confidence.
5. Start an investigation → watch the LangGraph plan → retrieve → verify →
   timeline state transitions.
6. Open the run → review the timeline, findings with weighted support, detected
   gaps, and the flagged contradiction.
7. Review a finding (accept / mark uncertain) → generate the incident report →
   open the PDF.

Every demo payload carries the banner `DEMO DATA — NOT REAL FORENSIC EVIDENCE`.

---

## 10. Defects Found and Resolved

Real defects found **during** verification — each reproduced before the fix and
re-verified after. This is the strongest evidence in the report that the
verification is genuine.

| # | Defect | Impact | Resolution |
|---|---|---|---|
| 1 | `reportlab` was not in `requirements.txt` | The "PDF" report silently degraded to markdown — **no PDF was ever produced** | Pinned `reportlab==4.2.5`; Phase 8 now renders a real PDF (46/46) |
| 2 | `GET /demo/dataset` raised `AttributeError` on a `null` thumbnail entry | HTTP 500 on the demo page | Non-dict entries skipped; downloader no longer writes `null` |
| 3 | Rolling frame buffer fed **relative** timestamps while evicting on **absolute** wall-clock time | `frames_buffered=0` — every frame instantly evicted; VLM and evidence grounding never saw a frame; `analyze` returned 429/409 | Feeders now stamp absolute `time.time()`; proven by before/after reproduction and back-to-back regression runs |
| 4 | `usb_camera.connect()` trusted `isOpened()` | A non-existent device reported itself healthy | Both transports read a real frame before reporting `opened=true` |
| 5 | Pydantic `DetectionObject` vs tracker dict-only contract | Would have **silently disabled tracking in production** | `_normalize_detections` adapter |
| 6 | `active_tracks` was a cumulative counter | UI misreported live track count | Split into live `active_tracks` and cumulative `active_updates` |
| 7 | Torch 2.6+ `weights_only=True` default | Ultralytics 8.2.x checkpoints failed to load | Idempotent `torch.load(weights_only=False)` patch |
| 8 | `datetime` in `VlmRequest.context` | Broke `send_json` and disabled the VLM WebSocket entirely | `model_dump(mode="json")` at both producer seams |
| 9 | Latent `NameError` in `qdrant.delete()` | Evidence re-index would crash | Fixed; Qdrant point IDs canonicalised to stable UUID5 |
| 10 | De-duplication race between hash check and commit | Duplicate evidence under concurrency | `RLock` around check → store → commit |
| 11 | `live` console rendered black for backend-owned cameras | No preview for webcam / USB / file / simulation | MJPEG preview stream publishing the exact pipeline frames |
| 12 | Bounding-box overlay ignored letterboxing | Boxes misaligned on a 4:3 camera | Overlay maps absolute-pixel boxes onto the letterboxed content rect |
| 13 | Demo verifier asserted 6 videos / 5 cases; dataset has 10 | False verification failure | Assertions aligned to the documented 10-video / 10-case set |
| 14 | Nested storage directories not created | Local-filesystem storage fallback failed | `makedirs` in the local path resolver |
| 15 | `report/service.py` 2-argument `list.append` in the markdown fallback | Report generation crashed when ReportLab was absent | Fixed |

**Known pre-existing condition, reported rather than hidden.** Running
`verify_final_system.py` twice without an intervening `reset_demo_database.py`
makes the Phase 5 integrity check report orphaned references
(`analysis #6: 'EVD-DEMO-…' does not exist`). Cause: the demo reseeder deletes
`EVD-DEMO-%` evidence rows but leaves `forensic_analyses` rows referencing them.
This is **demo-reset tooling behaviour, not a live-pipeline defect** — evidence
created by a live session is never deleted. A clean `reset → seed → verify`
cycle reports Phase 5 PASS.

---

## 11. Challenges Faced and Mitigation

| Challenge | Why it was hard | Mitigation adopted |
|---|---|---|
| **No physical capture device reachable** | The container has no `/dev/video*`; Docker Desktop's WSL2 backend does not pass a host camera through | Refactored to a **single** transport-agnostic capture implementation with a `CameraSource` abstraction, so webcam / USB / file all share one path and the blocker is environmental, not architectural. Reproduction steps documented for the host. |
| **No VLM provider credentials** | A real multimodal run was impossible offline | Built a provider abstraction with a `simulation` backend that is *provenance-grounded and refuses to see pixels*. The offline validator honestly reports **2 PASS / 13 FAIL** for content cases precisely because the simulated model cannot observe imagery. This demonstrates the hallucination-detection harness works. |
| **Frames were being silently lost** | Symptom-free: counters read zero, no exception raised | Reproduced under back-to-back live sessions; fixed at the timestamp source rather than the symptom; added a regression test. |
| **PDF was never actually generated** | Graceful degradation masked a missing dependency | Root-caused, dependency pinned, and a verifier check added so it cannot silently regress. |
| **Determinism vs LLM variability** | An agent that hallucinates cannot be an evidence system | Kept the LLM out of the *deterministic* path: the query parser, planner, verifier and forensic stages are all deterministic, bounded and testable. Language composition is deliberately deferred. |
| **Prompt injection via evidence content** | Evidence text is untrusted input to the agent | `sanitize_evidence_text` + `is_observed_statement`; only literal `[OBSERVED]` content is citable. |
| **Contradictory detections** | The system could have "picked a side" and hidden a conflict | Conflicts are **surfaced, never resolved** — a deliberate design decision. |
| **Windows host constraints** | Path length (`WinError 206`) broke torch/ultralytics installs; `time.monotonic()` resolution ~15.6 ms caused one flaky timing test | Docker uses a short `/app` path; the flaky test's budget was widened; both documented. |
| **Long-path + CPU-only inference** | No GPU; ~140–600 ms/frame | Bounded buffers, newest-wins queues, sampling/decimation, and honest reporting of the real torch device. |

---

## 12. Ethical and Safety Compliance

These are enforced in code, not merely stated in documentation.

| Principle | Implementation |
|---|---|
| **No facial recognition / biometrics** | No face-detection or embedding model exists anywhere in the codebase. Detections are class labels only. |
| **No identity claims** | Tracks are visual IDs (`Person-000001`); the detector carries no name field. |
| **No intent inference** | A forbidden-substring guardrail lexicon in `app/vlm/schemas.py` blocks identity, name and intent claims from VLM output. |
| **No fabricated timestamps** | All timestamps derive from source video metadata. The client cannot supply pixels or timestamps — they are rejected. |
| **Immutable original evidence** | MinIO object lock (COMPLIANCE mode) on the videos bucket; evidence is content-addressed by SHA-256; reviewer decisions store an immutable snapshot. |
| **Explicit uncertainty** | Three abstention guardrails; finding status is `OBSERVED / INFERRED / POLICY-ASSESSED / VERIFIED / UNKNOWN`. Insufficient evidence produces an explicit *insufficient evidence* answer, not a guess. |
| **No cross-camera identity fusion** | Multi-camera correlation returns only `POSSIBLE_CORRELATION` or `UNKNOWN` — never `SAME_OBJECT`. |
| **No causal claims** | All sequencing relationships are `causal: false`. |
| **Human review mandatory** | `AGENT_REQUIRE_HUMAN_REVIEW=True`; a run must reach `READY_FOR_REVIEW` before a report is finalised. |
| **Full audit trail** | Every privileged action is recorded; admin-visible via `GET /audit/logs` and a dedicated UI screen. |
| **Demo data labelled** | Every demo payload carries `DEMO DATA — NOT REAL FORENSIC EVIDENCE`; internet test data is classified and segregated from evidence. |

---

## 13. Honest Limitations and Open Blockers

Nothing in this section is presented as complete. These are the items a reviewer
should weigh.

### 13.1 The single open blocker

**The physical camera chain is NOT TESTED.** The verification environment
(WSL2 container) exposes no capture device:

```text
$ verify_webcam.py --probe
WEBCAM PROBE (indices 0..3)
  no capture device produced a frame on indices 0..3
RESULT: NO DEVICE

$ ls /dev/video*
ls: cannot access '/dev/video*': No such file or directory
```

Consequently the following steps have **no evidence of success**:
`REAL FRAME → REAL YOLO → tracking → motion events → evidence capture → RAG →
LangGraph investigation → timeline → finding → human review → PDF`.
The webcam *code and tests* are implemented and verified; the *physical
round trip* is unproven. The MJPEG preview pipeline is proven independently
because it is transport-agnostic, but the picture on a laptop screen still
requires human eyes.

### 13.2 Full limitation register

| # | Limitation | Status |
|---|---|---|
| 1 | Physical webcam / phone-camera end-to-end | **NOT TESTED** — no device in environment |
| 2 | Real VLM provider (accuracy, faithfulness, latency) | **NOT TESTED** — no credentials |
| 3 | Real-network WebRTC: ICE / TURN / NAT traversal, actual peer media delivery | **NOT TESTED** |
| 4 | Detection accuracy (mAP) | **NOT EVALUATED** — plumbing and contracts proven, accuracy not measured |
| 5 | Tracking accuracy (ID persistence, occlusion, re-acquisition) | **NOT EVALUATED** — real-YOLO-into-tracker path never run together |
| 6 | GPU inference / multimodal throughput at scale | **NOT MEASURED** — CPU only; no GPU claim is made |
| 7 | Full labelled evaluation benchmark | **NOT AUTHORED** — therefore no published accuracy figure |
| 8 | LLM-composed natural-language answers | **DELIBERATELY DEFERRED** — deterministic path only |
| 9 | Long-horizon evidence volume / sustained throughput | **NOT MEASURED** |
| 10 | Multi-camera case scope | Single-camera per run; conservative correlation by design |
| 11 | Browser-level visual smoke of `/demo` and live WebSocket UI | **NOT DEMONSTRATED** (`npx tsc --noEmit` / `npm run build` are the gates; `next lint` is not configured) |
| 12 | CI automation | **NONE** — pytest and `npm run build` are run manually |
| 13 | Login rate limiter is in-process | Fine for the single-worker demo; multi-worker deployment needs a shared store (Redis) |
| 14 | Demo reseeder leaves `forensic_analyses` orphans on a re-run | Known tooling condition, reported not hidden (§10) |
| 15 | Timeline capped at 200 entries | Declared bound, not a defect |
| 16 | `SECRET_KEY` ships with a development default | Overridden by env in every run; **must** be set in any real deployment |
| 17 | Documentation numbering inconsistency | The README roadmap's "Phase 1–9" does not match the `PHASE*_REPORT.md` series; needs reconciliation |
| 18 | ReportLab version discrepancy | `requirements.txt` pins `4.2.5`; the Phase 8 body text mentions `5.0.1`; the pinned version is authoritative |

### 13.3 Current official verdict

> **`FINAL STATUS: NOT READY`** — the single blocker is that the physical
> laptop/phone camera is not reachable from the verification environment, so
> the live camera chain has no evidence of success. Every other component is
> verified against real services.

This verdict is reported as-is. It will be upgraded to **READY** the moment
`verify_live_webcam.py` completes on a host with a reachable device, and that
single command is the top priority of the next cycle.

---

## 14. Plan for the Next Reporting Cycle

### 14.1 Priority 1 — Close the blocker

1. Run `verify_webcam.py --probe` and `verify_live_webcam.py` on a **host-native**
   backend (not the container) to complete the physical chain:
   `REAL FRAME → YOLO → tracking → events → evidence → PostgreSQL → MinIO →
   Qdrant → VLM → investigation → timeline → review → PDF`.
2. Execute the acceptance test: place real objects in front of the camera and
   confirm correct detection, tracking and event generation.
3. Re-run `verify_final_system.py` and publish the updated status matrix.
4. Document the browser-level visual check of the Live Console preview and
   bounding-box overlay on a real 4:3 and a 16:9 stream.

### 14.2 Priority 2 — Real VLM integration

1. Configure a real OpenAI-compatible VLM endpoint.
2. Re-run the offline grounding validator; target a real PASS on the 13 content
   cases that currently FAIL under `simulation`.
3. Re-measure VLM latency and assess faithfulness on real footage.
4. Keep the `simulation` backend as a tested offline fallback.

### 14.3 Priority 3 — Evaluation (closes limitation 7)

1. Author `data/evaluation/benchmark.jsonl`: query, expected event, expected
   timestamp, relevant clip, expected answer — across the 12 existing scenarios.
2. Implement the metric suite: Recall@5/@10, Precision@5, MRR, timestamp error,
   temporal IoU, context relevance/recall, answer faithfulness, hallucination
   rate, processing time, query latency.
3. Publish a baseline-vs-system comparison in the next report.

### 14.4 Priority 4 — Accuracy and performance measurement

1. Run a real-YOLO-into-tracker evaluation (closes limitations 4 and 5):
   detection counts, ID-switch rate, occlusion recovery.
2. Profile and report sustained-throughput figures (limitation 9).

### 14.5 Priority 5 — Delivery quality

1. Wire CI to run `pytest` and `npm run build` on every change (limitation 12).
2. Add a configured linter so `npm run lint` is a real gate (limitation 11).
3. Fix the demo-reseed orphan condition in
   `seed_demo_evidence._wipe_demo_evidence()` (limitation 14).
4. Reconcile the phase-numbering discrepancy between the README roadmap and the
   `PHASE*_REPORT.md` series (limitation 17).
5. Move the login rate limiter to a shared store for multi-worker readiness
   (limitation 13).
6. Produce a final consolidated report and a recorded demonstration video.

---

## 15. Conclusion

Progress Report 1 covers the delivery of a **working, verified, evidence-grounded
GenAI forensic investigation platform** across ten increments.

The project has moved past the prototype stage in the sense that matters for an
academic evaluation: the central claim — *that an AI system can answer
investigative questions about long-form surveillance footage and show its work* —
is now demonstrated end to end against real PostgreSQL, MinIO and Qdrant, with
430 automated tests passing, four phase verifiers green, an 11-stage
end-to-end verification passing, and a 196-check demo dataset verification
passing.

Equally, the report's value lies in what it does **not** claim. The system is
reported as `NOT READY` because one chain — the physical camera — has no
evidence of success in the available environment. The real VLM provider has not
been run. Detection and tracking accuracy have not been measured. No published
accuracy figure is offered, because no benchmark has yet been authored. The
research team considers a report that overstated its verification to be a failed
deliverable, and this one is written accordingly.

The next cycle is well defined: close the physical-camera blocker, integrate a
real VLM, and author the evaluation benchmark that will allow objective accuracy
claims to be made for the first time.

---

## Appendix A — Artifact Index

### A.1 Code

| Area | Path | Purpose |
|---|---|---|
| FastAPI app | `backend/app/main.py` | App, CORS, lifespan |
| Config | `backend/app/core/config.py` | All tunables (60+ settings) |
| Auth / RBAC | `backend/app/auth/` | JWT, roles, rate limiting |
| Video pipeline | `backend/app/video/` | FFmpeg, scene detection, clips, processor |
| Live runtime | `backend/app/live/` | `manager.py`, `ingestion.py`, `webrtc.py`, `webcam_camera.py`, `usb_camera.py`, `sampler.py`, `rolling_buffer.py`, `feeds/` |
| Detection | `backend/app/detection/` | YOLO engine, worker, metrics, schemas |
| Tracking | `backend/app/tracking/` | IoU tracker, motion, event detector |
| VLM | `backend/app/vlm/` | Selection, preprocess, triggers, worker, session |
| Evidence | `backend/app/evidence/` | Paths, capture, indexer, schemas |
| Video RAG | `backend/app/investigation/` | Query parser, retrieval, rerank, answers |
| Agent | `backend/app/investigator/` | LangGraph planner, tools, agent, conflicts |
| Forensic | `backend/app/forensic/` | Timeline, verification, gaps, sequencing, report |
| Policy RAG | `backend/app/rag/`, `backend/app/policies/` | Document chunking and policy retrieval |
| Storage | `backend/app/storage/service.py` | MinIO / local FS with object lock |
| Models | `backend/app/database/models.py` | 18 ORM entities |
| Migrations | `backend/alembic/versions/` | `0001` → `0008_phase8_forensics` |
| Frontend | `frontend/app/` | 20 routes (live, search, evidence, investigations, runs, reports, policies, demo, audit, videos, settings) |
| Tests | `tests/` | 42 modules, 430 tests |

### A.2 Reports (this period)

`PHASE1_REPORT.md` · `PHASE2_REPORT.md` · `PHASE3_REPORT.md` ·
`PHASE4_REPORT.md` · `PHASE4_REPORT_vlm_grounding_internet_testdata_PRIOR.md` ·
`PHASE5_REPORT.md` · `PHASE6_REPORT.md` · `PHASE7_REPORT.md` ·
`PHASE8_REPORT.md` · `PHASE9_SYSTEM_AUDIT.md` · `PHASE9_REPORT.md` ·
`PHYSICAL_CAMERA_REPORT.md` · `FINAL_SYSTEM_REPORT.md` ·
`DEMO_INVESTIGATION_REPORT.md` · `DEMO_VIDEO_DATASET.md` ·
`WEBCAM_SETUP.md` · `PHYSICAL_CAMERA_SETUP.md`

### A.3 Documentation

`docs/ARCHITECTURE.md` · `docs/OPERATIONS.md` · `docs/DEMO_GUIDE.md` ·
`docs/TROUBLESHOOTING.md` · `docs/SECURITY.md` · `README.md` ·
`abstract.md` · `Document/` (PRD, improved documentation, prototype README)

### A.4 Machine-readable verification output

`backend/data/demo_investigation/results/phase9_e2e_results.json` ·
`verification_all_results.json` (196 checks) · `verification_results.json` ·
`seed_summary.json`

---

## Appendix B — Reproduction Commands

```bash
# 0. Infrastructure
cd ai-forensic-investigation
cp .env.example .env          # set SECRET_KEY to a strong random value
docker compose up -d --build

# 1. Full automated test suite
python -m pytest -q                        # expect: 430 passed

# 2. Frontend production build
cd frontend && npm run build               # expect: clean, 20 routes

# 3. Per-phase verifiers against live services
python backend/scripts/verify_phase5.py    # evidence, PostgreSQL, MinIO, Qdrant, integrity
python backend/scripts/verify_phase6.py    # Video RAG
python backend/scripts/verify_phase7.py    # LangGraph agent
python backend/scripts/verify_phase8.py    # forensic timeline, verification, report + PDF

# 4. End-to-end (11 stages)
python backend/scripts/run_full_e2e.py     # expect: 11 stages, 0 FAILED

# 5. Demo dataset
python backend/scripts/verify_demo_dataset.py     # 196 checks
python backend/scripts/verify_evidence_integrity.py

# 6. PHYSICAL CAMERA (the open blocker — run on a host-native backend)
cd backend
python scripts/verify_webcam.py --probe                  # list devices 0..3
python scripts/verify_webcam.py --device 0 --seconds 10 # capture test
uvicorn app.main:app --reload
python scripts/verify_live_webcam.py --base-url http://127.0.0.1:8000 --device 0 --seconds 45

# 7. Consolidated final status matrix
python backend/scripts/verify_final_system.py --base-url http://127.0.0.1:8000
# prints: FINAL STATUS: READY | NOT READY
```

---

**End of Progress Report 1**

*Prepared 2026-09-28. All verification figures in this report are reproducible
using the commands in Appendix B. Items marked NOT TESTED are stated as such and
are not counted as successes.*
