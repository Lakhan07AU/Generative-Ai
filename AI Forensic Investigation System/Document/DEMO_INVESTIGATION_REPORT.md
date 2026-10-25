# Demo Investigation Dataset & Demo Mode Report (DEMO_INVESTIGATION_REPORT)

Date: 2026-09-12
Scope: End-to-end demo readiness of the AI Forensic Investigation System: a clearly
labeled, reproducible **10-video / 10-case / 12-scenario demo dataset** built on real,
publicly licensed sample clips, exercised through the real pipeline (CV2 → YOLO →
tracking → events → VLM → evidence → RAG → agent), with an idempotent seeder, a
canonical section-matrix verifier, a frontend demo dashboard, and honest measured
numbers.

Every section is classified **PASS / FAIL / PRE-EXISTING FAILURE / NOT TESTED**.
Everything reproduces from `backend/scripts/` with the API, Postgres, MinIO, and
Qdrant running.

---

## 1. Objective
**PASS.** Deliver the demo-ready dataset + demo mode described above without breaking
Phases 1–7. All constraints honored: every video/payload carries
`DEMO DATA — NOT REAL FORENSIC EVIDENCE`; no invented licenses, sources, events, or
performance; missing categories are documented; the system honestly abstains
(`UNKNOWN` / `INSUFFICIENT EVIDENCE`) where evidence does not exist; seeder is
idempotent; no concurrent `/process` runs (torch); existing infra reused, nothing
duplicated.

## 2. Dataset Composition
**PASS.** 10 real videos (DVS-001..DVS-010) drawn only from Intel
`intel-iot-devkit/sample-videos` (CC BY 4.0) and Big Buck Bunny via test-videos.co.uk
(CC BY 3.0). Covers: parking vehicles, street persons+bikes+cars, retail aisle,
public plaza, classroom, corridor one-by-one entry, worker zone, corridor walking,
walking + pause, and an animated cartoon (robustness/negative). 12 named scenarios
(SCN-01..SCN-12) in `metadata/manifest.json` + `scenarios/SCN-*.json`, each with
investigation query sets and expected observations covering **both** OBSERVED and
UNKNOWN classes. 10 case files (`cases.json`) map DVS→scenario→queries→observations→
expected events. 18 keyframes, 10 thumbnails, 2 negative fixtures (`not_a_video.mp4`,
`empty_static_scene.mp4`).

**Principle (documented in the dataset README):** every video has a stable,
scenario-agnostic **`stable_name`** (`demo_*.mp4`) while the physical file keeps its
`demo_video_XX_*` name — a deliberate reuse-over-rename design so DB/MinIO references
and uploaded records never break.

## 3. Seeding (idempotent)
**PASS.** `backend/scripts/seed_demo_videos.py` is manifest-driven and idempotent:
creates 18 demo cameras (id 14–18 newly), uploads all 10 files, polls each
`/process` job to completion sequentially (never concurrent), creates 10
investigations (7–8 inclusive net), and re-runs cleanly.

## 4. Live Upload / Processing Status
**PASS.** All 10 demo videos **READY** in the DB with real YOLO detections:

| video id | file id | DB status | detections | events |
|---|---|---|---|---|
| 5 | DVS-001 | READY | 32 | 0 |
| 6 | DVS-002 | READY | 66 | 6 |
| 7 | DVS-003 | READY | 2116 | 13 |
| 8 | DVS-004 | READY | 78 | 8 |
| 9 | DVS-005 | READY | 1175 | 7 |
| 12 | DVS-007 | READY | 360 | 26 |
| 13 | DVS-008 | READY | 145 | 15 |
| 14 | DVS-009 | READY | 89 | 9 |
| 15 | DVS-010 | READY | 195 | 14 |
| 16 | DVS-006 (cartoon) | READY | 7 | **0** |

Cartoon DVS-006 producing near-zero detections and **zero events** is the honest
outcome for entirely synthetic/non-permission content — used as the negative demo.

## 5. Demo API
**PASS.** `backend/app/api/demo.py` serves `/demo/dataset` (assets + scenario catalog
+ per-video metadata), `/demo/thumbnails/{demo_id}.jpg`, `/demo/keyframes/...`,
`/demo/scenarios`, `/demo/cases`, `/demo/investigation_queries/{scenario_id}`.
Thumbnails are available on disk for DVS-001..010; keyframes for the 9 content videos
(no keyframe for the cartoon). Verified live offline and online.

## 6. Frontend Demo Dashboard
**PASS.** `frontend/app/demo/page.tsx` renders: global `DEMO DATA — NOT REAL FORENSIC
EVIDENCE` banner; video cards with `demo_id` badge, thumbnail (served via
`api.demoThumbnailUrl`, not filesystem path), status badge, resolution/duration/fps,
stable name, scenario chips, license, and a "Run in Live" link; 12-scenario accordion
(event expectation + backing videos + OBSERVED/UNKNOWN question groups); demo cases
section. `frontend/lib/api.ts` exposes `demoScenarios`, `demoScenario`,
`demoThumbnailUrl`, `demoKeyframeUrl`, `demoInvestigationQueries`; `liveStart`
accepts `video_path`. `npm run build` passes.

## 7. Verification (section matrix)
**PASS.** `backend/scripts/verify_all_demo_videos.py` — canonical verifier: 196 checks,
**0 failures**, all 7 sections PASS (`results/verification_all_results.json`).

| Section | Result | Coverage |
|---|---|---|
| DATASET | PASS | 10 files + SHA-256, licenses, 12 scenarios, 10 cases, OBSERVED/UNKNOWN observations, not_a_video fixture |
| UPLOAD | PASS | 10/10 uploaded + READY with real detections |
| LIVE | PASS | real file-transport session: 641 frames received/sampled, 585 detection frames, 349 detections, 4 evidence captured + 4 indexed in Qdrant |
| RAG | PASS | grounded + ungrounded queries; honest UNKNOWN abstention on identity/intent questions |
| AGENT | PASS | 10 CASE-DEMO investigations; Phase 7 run COMPLETED with answer; runs list; Phase 6 chat; timeline 200 |
| NEGATIVE | PASS | cartoon near-zero detections + 0 events; not_a_video upload rejected |
| SECURITY | PASS | disclaimer labeling on every payload; no demo video in FAILED state |

Honest measured live-run numbers (from the last verification run, not invented):
frames received/sampled **641/641**; detection frames processed **585**; detections
**349**; inference avg **~212 ms/frame**; VLM observations **4**; evidence
captured/indexed **4/4**.

## 8. RAG / Investigation Search Behavior
**PASS (honest by design).** `/rag/query` and `/investigation/search` over the
offline-processed demo clips correctly return `UNKNOWN - INSUFFICIENT EVIDENCE`
(identity/intent/outside-view questions abstain, matching the Phase 6 grounded-answer
policy). Grounded, evidential answers exist only where live-captured evidence was
indexed; the verifier's live run adds 4 such items, and the agent run produces an
honest abstention when verification confidence is below threshold.

## 9. Regression
**PASS (with documented pre-existing issues).**
- `tests/test_demo_investigation.py`: **34 tests pass** (10-video/10-case manifest,
  SHA-256, licenses, cases, scenarios, keyframes/fixtures, negative fixtures, real
  CV2 file feeder, offline demo API).
- `tests/test_investigations.py`, `tests/test_investigator_phase7.py`,
  `tests/test_investigation_search.py`, `tests/test_reports.py`: all pass.
- Full suite: only **6 pre-existing `tests/test_evaluation.py` failures** remain
  (missing `data/evaluation/benchmark.jsonl` — out of scope). One
  concurrency-sensitive `test_live_api.py::test_unsupported_transport_422` is flaky
  when the shared test DB is polluted by other runs; it passes in isolation.

## 10. Bugs Fixed During Verification (PRE-EXISTING FAILURES, now resolved)
- **`investigation_runs` table missing** in the live Postgres (Phase 7 model exists,
  migration `0007_phase7_investigator` was never applied) → agent runs returned 500.
  Fixed by additive-only `Base.metadata.create_all` (creates the missing table,
  touches no existing data). Agent runs now complete.
- **`TimelineEventOut.evidence_ids` schema mismatch**: DB stores a JSON string in a
  Text column but the schema demanded `List[str]` → `/investigations/{id}/timeline`
  returned 500. Added a `field_validator` mirroring the file's existing
  `_parse_checks` pattern. Timeline now 200.
- **`report/service.py` markdown fallback crash**: `lines.append(f"## …", "")`
  (2-arg list append) broke report generation when ReportLab is absent. One-line fix;
  `tests/test_reports.py` green.

## 11. Remaining / NOT TESTED
**NOT TESTED.** Browser-level visual smoke test of `/demo` (the build passes and the
API endpoints were verified live; the page itself was not rendered in a browser this
session). Live-websocket UI (watching the live stream in the browser) was not
demonstrated. These do not affect dataset readiness.

---

## Verdict

**DEMO DATASET READY**