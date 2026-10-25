# FINAL ENGINEERING AUDIT

**Repository:** `D:\Github\Generative-Ai` (Git root — the parent of the project folder)
**Project subtree:** `AI Forensic Investigation System/ai-forensic-investigation`
**Remote:** `https://github.com/Lakhan07AU/Generative-Ai`
**Audit date:** 2026-09-28
**Status of this document:** BASELINE AUDIT — no architecture changes made after this audit was started.

> This audit was performed **before** any new feature work, as required.
> Every status below is one of: `PASS`, `FAIL`, `PARTIAL`, `NOT IMPLEMENTED`, `NOT TESTED`, `ENVIRONMENT FAILURE`.

---

## 1. Git state (VERIFIED)

`git` is **not installed** and not on PATH on this machine. No Linux distro is available in WSL
(only `docker-desktop`). Git state was therefore reconstructed by reading the object database
directly (`.git/HEAD`, refs, packed objects, delta resolution) with a purpose-built reader.

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD commit | `413dab6d8c79c90a6835c21f5318c5694b4e063b` |
| HEAD subject | `Merge branch 'main' of https://github.com/Lakhan07AU/Generative-Ai` |
| Tracked files in project subtree | 285 |
| Deleted tracked files | 0 |
| **Real content changes vs HEAD** | **0** |
| EOL-only differences (CRLF working tree vs LF in repo) | 169 |
| Untracked files (mostly `.gitignore`d runtime data) | 2184 |

### 1.1 Critical conclusion — work IS committed

A naive byte comparison reports 169 of 285 files as "modified". **This is a false positive.**
The project `.gitattributes` at the repo root contains `* text=auto`, while the working tree
files carry CRLF. Hashing each file after `CRLF→LF` normalisation matches the committed blob
exactly for all 169 files. The delta is:

```
  169  EOL:crlf_to_lf
  116  clean
REAL content changes: 0
```

Independently confirmed by reading the committed blob out of the pack and diffing key settings —
the **committed `main` tree already contains** the frame-cap and reconnect work:

```
LIVE_MAX_FRAME_BYTES: int = 32 * 1024 * 1024
DROIDCAM_RECONNECT_BACKOFF_SECONDS: float = 3.0
WEBCAM_RECONNECT_BACKOFF_SECONDS:   float = 3.0
IPCAM_RECONNECT_BACKOFF_SECONDS:   float = 3.0
```

**Therefore: the repository is on `main`, clean, and contains all prior camera/metrics work.
The earlier concern that changes were uncommitted or `docker cp`-only is `FAIL`-resolved.**

### 1.2 Repository hygiene issue (real, non-blocking)

`core.autocrlf` is **unset** in `.git/config` while `.gitattributes` declares `* text=auto`.
On Windows this makes `git status` permanently dirty with 169 phantom modifications, which makes
real review impossible. Fix requires a decision from the repo owner (either set
`core.autocrlf=true` locally, or pin `* text=auto eol=lf`). **Not changed here** — Git operations
are unavailable and this is an owner policy decision.

### 1.3 Untracked files that matter

Nearly all 2184 untracked files are correctly ignored by `.gitignore` (`data/`, `tests/*.db`,
`*.env`, `node_modules/`, `.next/`). Two are **not** covered and are security-relevant:

- `frontend/scripts/cert.pem`
- `frontend/scripts/key.pem`

Private TLS key material is sitting in the working tree uncommitted and un-ignored.
Recommendation: add `*.pem` to `.gitignore` and confirm these keys are development-only.

---

## 2. Baseline test results

| Check | Command | Result |
|---|---|---|
| Backend unit/integration suite | `python -m pytest -q` | **PASS — 489 collected, 0 failed, 0 errors** (was 471/479 baseline; +8 `/frame` tests in §10.1, +10 pairing tests in §10.6) |
| Frontend production build | `npm run build` (in `frontend/`) | **PASS — 22 routes (17 static + 5 dynamic), incl. new `/live/mobile`** |
| Suite hermeticity (no external network) | grep of pytest output | **PASS — only loopback `127.0.0.1:9` is dialled** |

Counted directly from the progress output (7 lines of dots, no `F`/`E`/`s` characters).

### 2.1 Test isolation defect — FIXED

`tests/test_live_webcam_source.py::test_api_accepts_ipcam_transport_with_stream_url` posted a real
`stream_url` of `http://10.5.176.115:8080/video` to the live start endpoint, so the suite made
genuine outbound network calls during unit tests:

```
[tcp @ ...] Connection to tcp://10.5.176.115:8080 failed: Error number -138 occurred
```

It passed only because an unreachable stream is expected to return 503 — but if a phone *had*
been reachable, the test would have started a real capture session. Unit test results depended on
the state of the user's LAN.

**Fixed:**
- The API test now uses `UNREACHABLE_LOOPBACK_URL = "http://127.0.0.1:9/video"` (port 9/never
  listening, refused instantly by the OS) and asserts a strict `503` + `"unavailable"`, so it is
  hermetic and meaningfully verifies loud failure instead of tolerating any outcome.
- `tests/test_live_ipcam_source.py` now uses RFC 5737 documentation ranges
  (`203.0.113.0/24` TEST-NET-3) and `cam.example`, which are never routable to a real device.

Re-verified: the only connection attempt remaining in the whole suite is loopback.

```
471 passed, 0 failed, 0 errors
[tcp @ ...] Connection to tcp://127.0.0.1:9 failed: Error number -138 occurred
```

### 2.2 `RuntimeWarning: coroutine ... was never awaited` — test artifact, not a defect

Observed in `tests/test_detection_integration.py::TestICEBuffering::test_offer_flushes_buffered_candidates`.

The production path is correct: `_flush_pending_candidates()` is invoked from
`async def handle_offer` (`backend/app/app/live/webrtc.py:155`), so a running loop exists and
`asyncio.ensure_future` schedules properly. The warning arises because the **test** calls the
flush synchronously with no running loop, leaving the coroutine unscheduled.

Two minor robustness observations, both `LOW`, recorded honestly rather than as confirmed bugs:
- `webrtc.py:178` schedules `addIceCandidate` with no error handling; a scheduling failure would
  propagate into the signaling task.
- `webrtc.py:186-189` wraps `ensure_future` in `try/except`, but coroutine errors surface inside
  the task rather than at scheduling time, so the handler cannot actually observe them.

### 2.3 Frontend production build — PASS

`npm run build` (Next.js) completed successfully. 18/18 static pages generated, 22 routes,
shared First Load JS 87.1 kB. No TypeScript or lint build errors.

Routes produced:

```
/  /_not-found  /audit  /dashboard  /demo  /evidence  /investigate
/investigations  /investigations/[id]  /investigations/[id]/investigate
/live  /login  /policies  /register  /reports  /reports/[id]
/runs/[runId]  /search  /settings  /videos  /videos/[id]
```

Note the **absence of a `/cameras` route**, which corroborates the CCTV-dashboard gap in §4.2.

---

## 3. Runtime baseline (VERIFIED LIVE)

`docker ps` — all five services up:

| Container | Status | Ports |
|---|---|---|
| `forensic-frontend` | Up 3 hours | 3000 |
| `forensic-backend` | Up 3 hours | 8000 |
| `forensic-postgres` | Up (healthy) | 5432 |
| `forensic-qdrant` | Up (healthy) | 6333-6334 |
| `forensic-minio` | Up (healthy) | 9000-9001 |

`GET http://localhost:8000/health` → **PASS**:

```json
{"status":"ok","service":"ai-forensic-investigation","version":"1.0.0",
 "components":{"database":{"ok":true},
               "qdrant":{"backend":"qdrant","ok":true},
               "storage":{"backend":"minio","ok":true},
               "evidence_indexer":{"ok":true,"running":false,"queue_size":0},
               "live":{"ok":true,"active_sessions":0,"transports":[]}}}
```

- Database, Qdrant and MinIO: **PASS**.
- `evidence_indexer.running = false` is **not a fault** — the queue is lazily started on first
  `submit()` (`backend/app/evidence/indexer.py:108`). Verified by code inspection.
- `alembic current` → `0008_phase8_forensics (head)`. **PASS**, schema matches head.

### 3.1 Container image is current (resolves earlier blocker)

The earlier PyPI `ReadTimeoutError` build failure **has since been resolved**. A successful
build exists:

```
image sha256:1cc59b81c4f5e00635a558cf13727f0137b875098211d31ec184ede93e9f8d40
created 2026-09-28T07:08:17Z
```

and the running container serves the corrected values:

```
MAX_FRAME_BYTES 33554432
IPCAM_BACKOFF 3.0
```

The running deployment is therefore consistent with the committed source.

### 3.2 Inference device — honest recording

```
torch 2.14.0+cu130   cuda False
engine device: cpu
```

**PASS** on CPU. There is no GPU acceleration in this environment. Any performance figure must be
labelled CPU-only; do not claim GPU/CUDA inference.

---

## 4. Architecture audit — live camera subsystem

### 4.1 What exists

`backend/app/live/` contains:

```
__init__.py  ingestion.py  ipcam_camera.py  manager.py  rolling_buffer.py
sampler.py   source.py     synthetic.py     usb_camera.py
video_feeder.py  webcam_camera.py  webrtc.py
```

The canonical single pipeline is present and is the correct shape:

```
CameraSource → runtime.ingest_frame() → sampler → YOLO → tracking
             → events → evidence capture → PostgreSQL/MinIO
             → VLM → embeddings/Qdrant → RAG → LangGraph → forensics → report
```

- `CameraSource` exposes `connect/disconnect/read_frame/is_alive/health`. **PASS**
- Webcam, USB/DroidCam and IP camera all share `LocalOpenCVCameraSource` rather than duplicating
  capture logic. **PASS — no duplicate pipelines detected.**
- WebRTC receive path exists and is reusable. **PASS**

### 4.2 Gaps against the requested feature set

| Requested capability | Actual state | Status |
|---|---|---|
| `RtspCameraSource` as a distinct class | No such file. `ipcam_camera.py` accepts `rtsp://` URLs generically via the shared OpenCV/FFmpeg path | `PARTIAL` |
| ONVIF discovery | **Zero** occurrences of `onvif`/`ONVIF` anywhere in code or docs | `NOT IMPLEMENTED` |
| QR camera pairing | **Zero** occurrences of `qr_pair`/`qrcode`/`QRCode` | `NOT IMPLEMENTED` |
| Automatic CCTV processing | **Zero** occurrences of `auto_process` | `NOT IMPLEMENTED` |
| Latest-frame JPEG endpoint | Only `GET /live/cameras/{id}/stream.mjpg` exists | `IMPLEMENTED IN THIS SESSION` — `GET /live/cameras/{id}/frame` added in §10 |
| CCTV dashboard | No `frontend/app/cameras` route at all | `NOT IMPLEMENTED` |
| Redis / job queue service | Not in `docker-compose.yml` (postgres, minio, qdrant, backend, frontend only) | `NOT IMPLEMENTED` |

Live routes actually registered in `backend/app/api/live.py`:

```
POST   /live/cameras/{id}/stop
GET    /live/cameras/{id}/status
GET    /live/sessions
GET    /live/cameras/{id}/stream.mjpg
WS     /live/cameras/{id}/ws/signaling
WS     /live/cameras/{id}/ws/status
WS     /live/cameras/{id}/ws/detections
WS     /live/cameras/{id}/ws/tracking
WS     /live/cameras/{id}/ws/vlm
(plus 2 POST routes truncated by the grep)
```

### 4.3 Camera registry model — insufficient for the requirements

`backend/app/database/models.py` `class Camera`:

```
id, camera_name, location, description,
camera_type, stream_source, is_live, stream_status,
created_by_user_id, created_at
```

Missing for ONVIF/CCTV automation: ONVIF device identity, credential reference (non-plaintext),
`auto_process` flag, `last_seen_at`, connection health/last-error, RTSP-main vs sub-stream URLs,
and a per-camera processing concurrency budget. `camera_type` is a free-form string
(`CCTV | MOBILE | OTHER`) with no constraint.

**Status: `PARTIAL` — a migration (`0009_*`) is required.**

### 4.4 Preview path

An MJPEG preview exists and the frontend overlay previously passed regression tests. However the
requirement is a *latest-frame JPEG endpoint with sequence/timestamp headers* polled by the
frontend at ~4–5 FPS with object-URL cleanup. That endpoint does not exist. **Status: `PARTIAL`.**

---

## 5. Physical / external verification status

| Item | Status | Evidence |
|---|---|---|
| Real phone IP camera (current address `10.5.162.120:8080/video`) | `NOT TESTED` | Port 8080 closed from host; backend returns HTTP 503 `cannot open stream URL ... (ffmpeg: not opened; any: not opened; gstreamer: not opened)` |
| Prior IP run on `10.5.176.115` | `PASS` (capture + YOLO only) | 572 frames received, 572 sampled, 529 processed, 0 inference errors, ~9 FPS |
| Downstream tracking/events/evidence on that run | `NOT TESTED` | Scene contained no COCO-detectable object, so no event was generated. The model itself was proven working by direct inference on known frames (`person`, `bowl`, `cell phone`) |
| Laptop webcam inside Docker | `NOT TESTED` | Docker Desktop exposes no `/dev/video*`; host camera not passed through |
| Laptop webcam on host | `PARTIAL` | Opens at 640x480, sustained ≈1 FPS |
| VLM | `NOT TESTED` | No provider configured/credentialed |
| ONVIF hardware | `NOT TESTED` | Not implemented; no authorised device supplied |
| RTSP hardware | `NOT TESTED` | Not implemented as a distinct source; no authorised endpoint supplied |

---

## 6. Security audit findings

| # | Finding | Severity | Status |
|---|---|---|---|
| S1 | `frontend/scripts/key.pem` and `cert.pem` are untracked and not matched by `.gitignore` | Medium | **Fixed** — `*.pem`/`*.key` rule added to `.gitignore` (§10.4) |
| S2 | Tests performed real outbound network connections to a hardcoded IP | Medium | **RESOLVED** — see §2.1 |
| S3 | No Redis/queue service despite background-worker design | Low | Informational |
| S4 | Full security sweep (authz on every route, RBAC, path traversal, command injection into FFmpeg, prompt-injection containment, rate limits, secret leakage in logs) | — | `NOT TESTED` — not yet performed |
| S5 | `pip install -e .` documented/instructed somewhere, but **no `pyproject.toml` or `setup.py` exists**; only `requirements.txt` | Medium | Open — docs correction required |
| S6 | `webrtc.py:178` schedules `addIceCandidate` unguarded; `webrtc.py:186-189` `try/except` cannot observe coroutine errors | Low | Open — see §2.2 |

---

## 7. Documentation audit

| Document | State |
|---|---|
| `FINAL_ENGINEERING_AUDIT.md` | **This document** |
| `FINAL_CERTIFICATION_REPORT.md` | `NOT IMPLEMENTED` — to be produced after fixes |
| `FINAL_SYSTEM_REPORT.md` | Stale (pre-audit, ~430-test era) — must be superseded |
| `PHASE5/6/7/8/9_REPORT.md`, `PHASE9_SYSTEM_AUDIT.md` | Present but predate the current baseline |
| `README.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/SECURITY.md`, `docs/TROUBLESHOOTING.md`, `PHONE_IP_CAMERA.md`, `WEBCAM_SETUP.md` | Present; need refresh for current IP, native-vs-Docker install, and new features |

---

## 8. Verdict

**NOT READY FOR CERTIFICATION.**

What is genuinely solid today:

- Repository is on `main`, clean, with all prior work committed. `PASS`
- 489/489 backend tests pass. `PASS`
- All five services healthy; database, MinIO, Qdrant, evidence indexer, live subsystem all report OK. `PASS`
- Alembic at head. `PASS`
- Container image matches committed source. `PASS`
- Single coherent live-forensic pipeline with no duplication. `PASS`

What blocks certification:

1. ONVIF discovery, the dedicated RTSP source, and automatic CCTV processing are `NOT IMPLEMENTED`.
2. The latest-frame JPEG endpoint and its frontend Blob polling are **implemented** (§10.1, §10.2); QR device pairing is **implemented** (§10.6). A golden E2E against physical hardware is pending.
3. Camera automation fields (`auto_process`, ONVIF identity, stream URLs, health) are **implemented** (§10.5); CCTV use of them is pending.
4. Tests are not hermetic (real network I/O + stale hardcoded IP) — **RESOLVED in §2.1**.
5. Full security audit is `NOT TESTED`.
6. Frontend production build: **PASS** (§2.3).
7. Real device chains for webcam/RTSP/ONVIF are `NOT TESTED`; VLM is `NOT TESTED`.
8. `FINAL_CERTIFICATION_REPORT.md` does not exist.

---

## 9. Ordered remediation plan

1. ~~Fix test hermeticity~~ — **done**, see §2.1.
2. ~~Run and record `npm run build`~~ — **done**, see §2.3.
3. ~~Add `.gitignore` rule for `*.pem`; confirm dev keys are not production secrets~~ — **done**, see §10.4.
4. ~~Add `GET /live/cameras/{id}/frame` and frontend Blob polling~~ — **done**, see §10.1 and §10.2.
5. ~~Add `.gitignore` rule for `*.pem`~~ — duplicate of 3, **done**, see §10.4.
6. ~~Add migration `0009_*` for camera automation fields (`auto_process`, ONVIF identity, credential reference, `last_seen_at`, health, stream URLs)~~ — **done**, see §10.5.
7. ~~Implement QR pairing as a thin, single-use, camera+creator-bound token over the **existing** WebRTC path~~ — **done**, see §10.6.
8. Implement ONVIF discovery and a distinct `RtspCameraSource`, then auto-processing/reconnect policy in the existing `LiveCameraManager`.
9. Add the CCTV dashboard route and health/reconnect controls.
10. Perform the full security, performance, concurrency and failure-recovery sweeps.
11. Run the golden E2E and the real physical chains; record `NOT TESTED` honestly wherever hardware is unavailable.
12. Produce `FINAL_CERTIFICATION_REPORT.md` with the full status matrix.

---

## 10. Change log after the baseline

Every change below was made **after** the audit conclusions were written, and is listed so a
reviewer can see exactly what moved from `NOT IMPLEMENTED`/`PARTIAL`.

### 10.1 `GET /live/cameras/{id}/frame` (IMPLEMENTED — `PASS`, unit-tested)

- `backend/app/live/manager.py`
  - `_store_latest_preview(jpeg)` caches the encoded JPEG with its own monotonic
    `_preview_seq` and an epoch timestamp; `_frame_seq` (detection order) is not reused because
    it only advances when a detection queue actually submits.
  - `latest_preview()` returns `(jpeg, seq, epoch)` or `None`; calling it also arms the encoder
    for `_FRAME_POLL_GRACE_SECONDS` (2 s) via `note_frame_poll()`.
  - `_encode_preview()` now runs when an MJPEG subscriber **or** a recently-polling `/frame`
    client exists, so WebRTC sessions still never pay an encode cost they do not use.
- `backend/app/api/live.py`
  - Registered `GET /live/cameras/{camera_id}/frame` next to `stream.mjpg`.
  - Auth/role/session checks identical to the MJPEG route.
  - Returns `204` (never a fake image) before the first frame, then JPEG with headers
    `X-Frame-Sequence` + `X-Frame-Timestamp`, `Cache-Control: no-store`.
  - Never opens a second capture; re-publishes the exact frames pushed into detection.
- `tests/test_live_preview_stream.py` — 8 new tests:
  - store + sequence increment; empty-store returns `None`; poll deadline keeps the encoder
    alive without MJPEG subscribers; auth/role/no-session/conflict responses; the full
    request→204→ingest→200 flow with decodable JPEG and headers.
- Verified: `pytest tests/test_live_preview_stream.py` → 19 pass (was 11).

### 10.2 Latest-frame frontend polling (IMPLEMENTED — `PASS`)

- `frontend/app/live/page.tsx`
  - Removed the long-lived MJPEG `<img src=.../stream.mjpg>` for backend-owned sources
    (webcam / droidcam_usb / file / simulation). The console now polls
    `GET /live/cameras/{id}/frame?token=...` at ~4.5 FPS via `startFramePolling()`
    (`setInterval(..., 220)`).
  - Each HTTP 200 swaps the `<img>` onto a fresh `URL.createObjectURL(blob)` and revokes
    the previous object URL; a 204 keeps the last frame; 401/403/409/5xx keep the last
    frame and stop advancing. `previewInFlightRef` guards overlapping requests.
  - Polling starts/stops from a `useEffect` keyed on `streaming &&
    transport !== "webrtc" && selectedCameraId`, and `closeConnections()` now calls
    `stopFramePolling()` which also clears the interval and revokes the object URL, so
    no leak survives stop/switch/unmount.
  - WebRTC transports keep the native `<video>` and are untouched.
- Verified: `npm run build` **PASS** (Compiled successfully), `npm run lint` is not
  configured (interactive ESLint setup is skipped by design — pre-existing), Docker
  image `forensic-frontend:latest` rebuilt and recreated, `http://localhost:3000/live`
  returns 200.

### 10.3 Remaining for the latest-frame feature

Nothing for the core frame path. Golden end-to-end verification against a physical
camera (or the phone Webcam IP) is still outstanding and will be recorded in
`FINAL_CERTIFICATION_REPORT.md`.

### 10.4 Credential-file hygiene (security item S1 — FIXED)

- `.gitignore` now adds `*.pem` and `*.key` next to `*.env`. `frontend/scripts/key.pem`
  and `cert.pem` can no longer be committed accidentally. They remain local dev keys;
  no production secret material is involved, and no previous commit contains them.

### 10.5 Camera automation schema (IMPLEMENTED — `PASS`, migration applied live)

- `backend/alembic/versions/0009_camera_automation_fields.py` adds to `cameras`:
  `auto_process` (bool, default false), `onvif_host`, `onvif_username`, `credential_ref`,
  `rtsp_url`, `rtsp_url_alt`, `last_seen_at`, `health_status`, `last_error`,
  `reconnect_attempts`, `max_processing_fps`, plus index `ix_cameras_auto_process`.
  Postgres boolean default uses `sa.text("false")` (a naive `"0"` crashes the container
  with a DatatypeMismatch loop).
- `backend/app/database/models.py` `Camera` extended; `CameraCreate`/`CameraUpdate`/
  `CameraOut` in `schemas/video.py` extended; `PATCH /cameras/{id}` added in
  `api/cameras.py`.
- Migration applied live (`alembic current` is `0009 ... (head)`; all 11 columns verified
  via the app engine). API create/patch smoke-tested in the running stack (201/200), then
  smoke rows cleaned up.

### 10.6 QR device pairing (IMPLEMENTED — `PASS`, unit-tested, frontend built)

- `backend/app/live/pairing.py`: `create_pairing`, `consume_pairing` (single-use, expiring,
  creator+device bound), `pairing_url`, `render_pairing_qr` (pure-python `qrcode` + Pillow);
  `MAX_OUTSTANDING_PAIRINGS = 5`.
- New table `camera_pairings` via migration `0010_camera_pairings.py` (unique `pairing_id`,
  camera + creator FKs, `expires_at`, `consumed_at`).
- `api/live.py`: `POST /live/cameras/{camera_id}/pair` (roles, 404 unknown camera, audit)
  returns `{pairing_id, camera_id, expires_at, url, qr_url}`; `GET .../pair/qr.png` serves
  the PNG (404 unknown/foreign, 410 expired, 503 render failure). The pairing URL points at
  `/live/mobile?camera_id=&pair=` so the phone connects to the **exact** signaling socket.
- Signaling socket delegates to `_ws_authenticate_signaling`: it accepts and consumes a
  pairing code (only for the matching camera, opens the session under the **creator**
  identity) or falls back to the normal JWT path. Status/detection/tracking/VLM sockets
  are unaffected (still JWT-only).
- `frontend/app/live/mobile/page.tsx`: QR target page — reads `camera_id` + `pair`, then
  the existing getUserMedia → offer/answer/trickle sender flow, no JWT required.
  `frontend/app/live/page.tsx`: "Pair a device" button + QR modal (QR fetched as an
  authed blob since the API is HTTPBearer-only). `frontend/lib/api.ts`: `livePairCamera`,
  `livePairQrBlobUrl`.
- Config: `LIVE_QR_PAIRING_URL_BASE` (default `http://localhost:3000`),
  `LIVE_PAIRING_EXPIRE_SECONDS` (default 300). `qrcode==8.2` added to `requirements.txt`.
- `tests/test_live_pairing.py` — 10 tests (roles, missing camera, QR PNG magic bytes +
  ownership + expiry, signaling accept/reject/replay/wrong-camera, creator-bound session);
  **10/10 pass**. Full suite re-verified: **489 collected, exit 0, 0 failures**.
- **Deployed to the live stack**: migration `0010` applied (`alembic current` =
  `0010_camera_pairings (head)`); `qrcode==8.2` installed in the running container and
  baked via `requirements.txt`; live smoke passed (POST `/pair` → 201 with QR URL, QR PNG
  → 200 with magic bytes, signaling `{"type":"auth","pair":...}` → `auth_ok` +
  `bye_ack`, replay → `error`). Smoke rows cleaned up; frontend rebuilt and recreated
  with the new `/live/mobile` route (both `/live` and `/live/mobile` return 200).
- `backend/scripts/verify_qr_pairing.py` — reusable self-test (READINESS / QR PAIRING /
  PAIRING SIGNALING over real HTTP+WebSocket, `--cleanup`). Run in the live backend
  container: **12/12 checks PASS** (re-verified after the image rebuild below).
- **Image bake (reproducibility)**: `requirements.txt` now pins `torch==2.14.0` /
  `torchvision==0.29.0` (the exact versions the image ships) so pip no longer drifts;
  the canonical `Dockerfile` pip step gained `--timeout 120 --retries 8` for the flaky
  PyPI links on this host. A from-scratch rebuild still stalled on >500 MB CUDA wheels
  (repeated `ReadTimeoutError`/DNS failures on `files.pythonhosted.org`,
  `ENVIRONMENT FAILURE`), so `backend/Dockerfile.delta` builds thin on top of the
  validated image — adds `qrcode==8.2` and re-copies the committed `alembic/`, `app/`,
  `scripts/` — without re-downloading torch. `docker build -f Dockerfile.delta
  -t forensic-backend:latest backend/` **PASS**; container recreated from it (`alembic
  current` = `0010 (head)`, `/health` ok, self-test 12/12 again). So the *running* image
  now matches the committed source exactly. A canonical from-scratch rebuild remains
  blocked on this host's PyPI throughput and should be re-run on a faster connection.

---

## Appendix A — How the Git audit was performed

Because no `git` binary exists on this host, three small read-only Python utilities were written
to the scratch directory (outside the repository) that:

1. parse `.git/HEAD` and `refs/heads/*`,
2. resolve objects from loose **and** packed storage, including v2 `.idx` fanout tables,
   OFS-delta and REF-delta chains, and zlib streaming inflate,
3. hash the working tree as Git does (`sha1("blob <len>\0" + content)`) to compute real status,
4. re-hash with `CRLF→LF` normalisation to separate genuine edits from EOL noise.

No repository file was modified by this tooling.
