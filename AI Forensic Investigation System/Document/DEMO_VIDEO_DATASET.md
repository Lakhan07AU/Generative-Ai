# Demo Investigation Video Dataset (DEMO_VIDEO_DATASET)

> **DEMO DATA — NOT REAL FORENSIC EVIDENCE**
>
> Every asset in this dataset is a publicly available sample clip used only to
> demonstrate the AI Forensic Investigation System. It depicts no real incidents,
> suspects, victims, or admissible evidence. **Nothing here may be used in a real
> investigation.** Every payload the system emits carries this disclaimer.

Date: 2026-09-12
Scope: A curated, licensed, re-runnable demo dataset of **10 real public videos**
exercising **12 named scenarios** through the real pipeline
(CV2 → YOLO detection → tracking → events → VLM → evidence → RAG → agent), an
idempotent seeder, a canonical section-matrix verifier, and a frontend demo
dashboard with card/thumbnail/status/scenario views.

Every section is classified **PASS / FAIL / PRE-EXISTING FAILURE / NOT TESTED**.
No performance numbers or evidence claims have been invented.

---

## 1. Objective — PASS
Deliver a clearly labeled, reproducible demo dataset of 8–12 real
CC-licensed videos covering 12 named scenario categories, each uploadable
through the real API and fully processed (detections, events, clips) so the
live pipeline, RAG, agent investigation, and frontend demo mode can all be
demonstrated honestly end-to-end.

## 2. Dataset Composition — PASS
10 videos (DVS-001..DVS-010), 18 keyframes, 10 thumbnails, 2 negative
fixtures, 12-scenario `scenario_catalog`, 10 demo cases.

| ID | Physical file | Stable name (scenario-agnostic) | Scene | Duration | Resolution | License |
|---|---|---|---|---|---|---|
| DVS-001 | `demo_video_01_parking_cars.mp4` | demo_vehicle_detection | Parking / vehicle lane | 30.2s | 768×432 | CC BY 4.0 (Intel) |
| DVS-002 | `demo_video_02_street_persons_bikes.mp4` | demo_multi_object_tracking | Street: persons/bikes/cars | 53.9s | 768×432 | CC BY 4.0 (Intel) |
| DVS-003 | `demo_video_03_retail_store_aisle.mp4` | demo_crowd_complex_scene | Retail aisle | 65.4s | 720×404 | CC BY 4.0 (Intel) |
| DVS-004 | `demo_video_04_public_people.mp4` | demo_person_detection | Public plaza | 49.7s | 768×432 | CC BY 4.0 (Intel) |
| DVS-005 | `demo_video_05_archive_classroom.mp4` | demo_prolonged_presence | Classroom | 32.8s | 1920×1080 | CC BY 4.0 (Intel) |
| DVS-006 | `demo_video_06_cartoon_robustness.mp4` | demo_vlm_scene_understanding | Animated cartoon | 10.0s | 640×360 | CC BY 3.0 (Blender BBB) |
| DVS-007 | `demo_video_07_one_by_one_person_detection.mp4` | demo_object_entry_exit | Corridor one-by-one | 139.4s | 768×432 | CC BY 4.0 (Intel) |
| DVS-008 | `demo_video_08_worker_zone.mp4` | demo_object_stopping | Industrial worker zone | 75.9s | 1920×1080 | CC BY 4.0 (Intel) |
| DVS-009 | `demo_video_09_face_demographics_walking.mp4` | demo_object_movement | Corridor walking | 61.0s | 768×432 | CC BY 4.0 (Intel) |
| DVS-010 | `demo_video_10_face_demographics_walking_pause.mp4` | demo_temporal_investigation | Corridor walking + pause | 90.9s | 768×432 | CC BY 4.0 (Intel) |

Each video has a **stable_name** (scenario-agnostic identity recorded in the
manifest + `scenario_catalog`) while the physical filename stays
`demo_video_XX_*` — a deliberate **reuse-over-rename** decision so DB/MinIO
references and uploaded records never break.

Source repositories (no invented licenses):
- Intel IoT DevKit `sample-videos` (archived Sep 2024) — CC BY 4.0
  (`https://github.com/intel-iot-devkit/sample-videos`).
- Big Buck Bunny 10s clip via test-videos.co.uk — CC BY 3.0 (Blender Foundation).

## 3. Scenario Catalog (12) — PASS
Definitions in `scenarios/SCN-*.json`, query sets in `investigation_queries/SCN-*.json`,
honest expectations in `expected_observations/`:

| SCN | Key | Backing videos |
|---|---|---|
| SCN-01 | person_detection | DVS-004, 002, 007, 009, 010 |
| SCN-02 | vehicle_detection | DVS-001 |
| SCN-03 | multi_object_tracking | DVS-002, 001 |
| SCN-04 | object_entry_exit | DVS-007, 003, 010 |
| SCN-05 | object_movement | DVS-009, 002, 003, 010 |
| SCN-06 | object_stopping | DVS-008, 010, 001 |
| SCN-07 | prolonged_presence | DVS-005, 008, 010 |
| SCN-08 | multiple_events | DVS-002, 010 |
| SCN-09 | temporal_investigation | DVS-010, 002 |
| SCN-10 | vlm_scene_understanding | DVS-006, 002 |
| SCN-11 | crowd_complex_scene | DVS-003, 004, 009 |
| SCN-12 | cctv_complete_investigation | DVS-001, 002 |

Expected observations cover **both** `OBSERVED` and `UNKNOWN` answer classes so
the VLM's honest abstention behavior is baked into the reference data.

## 4. Demo Cases (10) — PASS
`cases.json`: CASE-DEMO-001..010, one per video, each linked to its primary
scenario, `investigation_queries`, `expected_observations`, and `expected_events`
(per-video `expected_events/dvs-XX.json`, non-forensic reference data).

## 5. Seeding & Processing — PASS
`scripts/seed_demo_videos.py` (idempotent, manifest-driven, camera map by case)
created 18 demo cameras, uploaded + processed all 10 videos to READY, and created
10 CASE-DEMO investigations. Real detections per video, verified live against the API:

- DVS-002 street: person/bicycle/car/motorcycle (66 detections, 6 events)
- DVS-007 corridor: person 214 / skateboard 123 / etc. (360 detections, 26 events)
- DVS-008 worker zone: person 138 (145 detections, 15 events)
- DVS-009 walking: person 86 (89 detections, 9 events)
- DVS-010 walking-pause: person 187 (195 detections, 14 events)
- DVS-006 cartoon: 7 detections, **0 events** (honest near-null — correct)

## 6. Verification (section matrix) — PASS
`scripts/verify_all_demo_videos.py --base-url` → **196 checks, 0 failures**, all 7
sections PASS. Results: `results/verification_all_results.json`.

| Section | Result | Highlights |
|---|---|---|
| DATASET | PASS | 10 files + SHA-256, licenses, 12 scenarios, 10 cases, OBSERVED/UNKNOWN, not_a_video fixture |
| UPLOAD | PASS | 10/10 uploaded + READY with detections |
| LIVE | PASS | real file-transport run on DVS-002: 641 frames, 349 detections, evidence captured+indexed |
| RAG | PASS | grounded + ungrounded queries; honest UNKNOWN abstention on identity/intent |
| AGENT | PASS | 10 investigations; Phase 7 run COMPLETED with answer; chat + timeline OK |
| NEGATIVE | PASS | cartoon near-zero detections/events; not_a_video rejected |
| SECURITY | PASS | disclaimer labeling everywhere; no demo video in FAILED state |

Measured live-run numbers (honest, latest run):
frames received/sampled **641/641**; detection frames processed **585**;
detections **349**; inference avg **~212 ms/frame**; VLM observations **4**;
evidence captured **4**, indexed **4**.

## 7. Frontend Demo Mode — PASS
`frontend/app/demo/page.tsx` dashboard: video cards with `demo_id` badge,
thumbnail (`/demo/thumbnails/{demo_id}.jpg`), status badge, resolution/duration/
fps, stable name, scenario tags, license, "Run in Live" link; 12-scenario
accordion (event expectation, backing videos, OBSERVED/UNKNOWN question sets);
demo cases section. `frontend/lib/api.ts` exposes `demoScenarios`,
`demoScenario`, `demoThumbnailUrl`, `demoKeyframeUrl`, `demoInvestigationQueries`;
`liveStart` accepts `video_path`. Production build passes.

## 8. Regression — PASS (with pre-existing failures documented)
- BeautifulSoup… n/a. Demo suite (`tests/test_demo_investigation.py`):
  **34 tests pass** (10-video, 10-case manifest integrity, SHA-256, licenses,
  cases, scenarios, keyframes/fixtures, negative fixtures, real CV2 file feeder,
  offline demo API).
- `tests/test_investigations.py`, `test_investigator_phase7.py`,
  `test_investigation_search.py`, `test_reports.py`: all pass.
- Full suite: only the **6 pre-existing `tests/test_evaluation.py` failures**
  (missing `data/evaluation/benchmark.jsonl`) remain — out of scope. One known
  concurrency-sensitive live_api test is flaky when the shared test DB is
  polluted by other runs; it passes in isolation.

### PRE-EXISTING FAILURES FIXED DURING VERIFICATION
- **`investigation_runs` table missing** in the live Postgres (Phase 7 added the
  model, migration `0007_phase7_investigator` was never applied) → agent runs
  returned 500. Fixed by additive-only `Base.metadata.create_all` (creates the
  missing table, touches no data); agent runs now COMPLETE.
- **`TimelineEventOut.evidence_ids`** stored as JSON string (Text column) but
  schema expected `List[str]` → `/investigations/{id}/timeline` returned 500.
  Fixed with the same `field_validator` pattern already used by
  `VerificationOut._parse_checks`. Timeline now 200.
- **`report/service.py` markdown fallback**: `lines.append(f"## …", "")` (list
  append with 2 args) crashed reports when ReportLab was absent. Fixed.
  `tests/test_reports.py` now green.

---

## Presentation Flow (5–10 min, UI-only)

Prereqs: backend `:8000`, Postgres `:5432`, Qdrant `:6333`, MinIO `:9000` up;
frontend dev server running; login as
`demo.investigation@forensics-demo.com` / `demo-investigation-2026`.

1. **Open `/demo`** (2 min). Show the banner "DEMO DATA — NOT REAL FORENSIC
   EVIDENCE". Point at the 10 video cards: thumbnails, green READY badges,
   demo_id tags, scenario chips. Scroll the 12-scenario accordion and note the
   OBSERVED vs UNKNOWN question groups.
2. **Pick the street clip** (DVS-002, `.02_street_persons_bikes.mp4`) — click
   **Run in Live** (1 min). It streams the file through the real transport.
3. **Live pipeline** (2–3 min): watch detection bounding boxes, track IDs,
   event log (person_entered / object_stopped style), manual VLM observation,
   and evidence cards appearing; explain that evidence is indexed into Qdrant.
4. **Ask the system** (1–2 min): on `/search` run a grounded question about
   persons/bicycles; then ask an identity question and show the **honest UNKNOWN
   abstention** (the system refuses identity/intent — by design).
5. **Agent investigation** (1 min): open a CASE-DEMO investigation, run the
   Phase 7 agent, show the run COMPLETED with a grounded UNKNOWN/OBSERVED style
   answer, timeline, and the human-review gate.
6. **Negative honesty** (30 s): load the cartoon (DVS-006) — near-zero
   detections and zero events are shown as-is, no fake numbers.
7. Close with: every number measured live, `verify_all_demo_videos.py`
   section matrix (7/7 PASS), and the demo disclaimer.

---

## Files
- Dataset root: `backend/data/demo_investigation/` (`videos/`, `thumbnails/`,
  `images/`, `scenarios/`, `investigation_queries/`, `expected_events/`,
  `expected_observations/`, `cases.json`, `metadata/manifest.json`, `results/`).
- Scripts: `backend/scripts/download_demo_investigation_data.py` (sources +
  manifest), `gen_demo_scenarios.py` (scenarios/queries/observations/cases,
  idempotent), `seed_demo_videos.py` (canonical seeder),
  `verify_all_demo_videos.py` (section-matrix verifier).
- API: `backend/app/api/demo.py` (`/demo/dataset|scenarios|thumbnails|keyframes|cases|investigation_queries`).
- Frontend: `frontend/app/demo/page.tsx`, `frontend/lib/api.ts`.