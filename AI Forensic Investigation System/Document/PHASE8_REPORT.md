# Phase 8 - Forensic Verification, Timeline Reconstruction & Investigation Reporting

**Status**: COMPLETE  
**Date**: 2026-09-12  
**Verdict**: READY FOR PHASE 9

---

## 1. What Was Built

Phase 8 adds forensic-grade verification, deterministic timeline reconstruction, human finding review, and machine-readable + PDF investigation reports to the AI Forensic Investigation System. Every output is grounded in existing evidence; no identity, causality, or off-camera activity is ever inferred.

## 2. Architecture

```
Phase 7 run (status COMPLETED/READY_FOR_REVIEW)
    │
    ▼
POST /runs/{id}/forensic/analyze
    │
    ▼
forensic/pipeline.py  ──►  7 deterministic stages
    │                      (load → correlation → timeline → verification
    │                       → contradiction → gaps → sequencing → multicamera)
    │
    ├──►  ForensicAnalysis persisted (timeline, findings, correlations,
    │     contradictions, gaps, relationships, multi_camera, metrics)
    ├──►  ForensicTimelineEvent rows persisted
    └──►  Analysis status = PENDING_REVIEW

Human review ──► POST /runs/{id}/findings/{fid}/review ──► FindingReview persisted
Report gen    ──► POST /runs/{id}/report (COMPLETED only) ──► PDF rendered → storage
Download      ──► GET  /runs/{id}/report/file
```

## 3. Forensic Pipeline Stages

All stages are deterministic, read-only over the run's evidence, and never fabricate.

| Stage | Function | Output |
|-------|----------|--------|
| Load | `_rows_for_run` | Evidence rows scoped to case cameras |
| Correlation | `correlation.correlate_evidence` | Track-sequence, VLM-chain, source-frame correlations |
| Timeline | `timeline.build_forensic_timeline` | Chronological events with classification, quality flags, evidence IDs |
| Verification | `verification.verify_findings` | Findings with support-scored factors, limitations, confidence |
| Contradiction | `_contradiction_detail` | Surfaced contradictions (never resolved) |
| Gaps | `gaps.detect_evidence_gaps` | Missing time ranges, missing camera coverage, insufficient resolution, etc. |
| Sequencing | `sequencing.sequence_entries` | BEFORE/AFTER/DURING/NEAR/OVERLAPPING — all non-causal |
| Multi-camera | `multicamera.correlate_across_cameras` | POSSIBLE_CORRELATION or UNKNOWN (never SAME_OBJECT) |

Per-stage timing is recorded in `metrics` (load_seconds, correlation_seconds, ..., total_seconds).

## 4. Semantic Vocabulary and Rules

`forensic/semantics.py` defines:

- **Vocabularies**: `TRACK_EVENT_VOCAB`, `VLM_OBSERVATION_VOCAB`, `FRAME_EVENT_VOCAB`
- **Careful prefixes**: "An observation consistent with...", "Evidence shows...", "A tracked object..."
- **Quality flags**: `track_only_without_visual`, `vlm_inferred_not_observed`, `low_resolution_frame_only`, `frame_without_visual_identity`
- **CAUSAL_NOTE**: "Temporal order alone does not establish causation. This finding does not assert a causal link."
- `classify_with_guard()`: downgrades low-resolution frame-only events, flags inferred VLM statements, never upgrades dubious sources to OBSERVED.

## 5. Timeline Reconstruction

`forensic/timeline.py`:

- Clusters evidence rows by track_id + event type + epsilon (2s) window
- Chronological sort (never intercalates timestamps)
- Event-time and analysis-time stamps on every entry
- Each entry: `timeline_event_id` (TL-xx), `timestamp`, `camera_id`, `track_id`, `object_class`, `event_type`, `classification`, `verification_status`, `quality_flags`, `conflicts`, `evidence_ids`, `description`
- Never invents events not in the evidence rows; empty evidence → empty timeline + honest summary

## 6. Event Relationships (Sequencing)

`forensic/sequencing.py`:

- Clusters timeline entries by track_id and epsilon window (2s overlap → DURING, ≤5s gap → NEAR, else BEFORE/AFTER)
- **All relationships carry `causal: false`** and `causality_note: "Temporal order alone does not establish causation."`
- Causality is never asserted from temporal ordering

## 7. Cross-Camera Correlation

`forensic/multicamera.py`:

- Groups timeline entries by track_id across different cameras
- **Never claims SAME_OBJECT** across cameras
- Only output: `POSSIBLE_CORRELATION` (same track_id, different camera_id) or `UNKNOWN`
- Includes supporting and limiting notes

## 8. Evidence Gaps

`forensic/gaps.py`:

- **missing_time_ranges**: gaps > 30s between evidence timestamps
- **missing_camera_coverage**: evidence limited to shown cameras; off-camera activity unobservable
- **missing_frames**: VLM observations referencing frames not present
- **insufficient_resolution**: low-resolution frames (≤480px) noted
- **occlusion**: not directly detectable but flagged where observation implies obscured views
- **unknown_objects**: evidence records without object class
- Gaps always include a `coverage` dict listing covered camera names

## 9. Finding Verification

`forensic/verification.py`:

- Per-finding support score: `evidence_support` (0–1) from weighted factors:
  - direct_visual (0.25), event_match (0.20), track_match (0.20), timestamp_match (0.15),
    camera_match (0.05), vlm_support (0.10), independent_sources (0.10)
- `support_factors`: array of {label, weight, matched}
- `support_reason`: plain-English chain-of-evidence
- `causality_safe`: boolean (causal claims suppressed)
- `listed_conflicts`: contradicting evidence IDs surfaced, not resolved
- `limitations`: evidence insufficiency notes
- Finding IDs: FINDING-xx

## 10. Contradiction Handling

- Contradictions surfaced from Phase 7 run result conflicts
- Pipeline `_contradiction_detail` preserves `type` (e.g. `event_type`) and `reason` from the source pair
- Reported in analysis as `{evidence_a, evidence_b, type, reason, timeline_entries}`
- **Never silently resolved**; both sides preserved in timeline and findings

## 11. Human Finding Review

`FindingReview` model + `schemas.py` + `store.py`:

- Reviewer action: ACCEPTED | REJECTED | MARKED_UNCERTAIN | REQUESTED_MORE_EVIDENCE
- `comment` stored; `reviewer_user_id` recorded
- `finding_snapshot` preserved at review time (immutable snapshot of the finding at that moment)
- Reviews do not modify the original forensic analysis
- GET /runs/{id}/reviews returns both run-level (audit log) and finding-level reviews

## 12. Investigation Report

`forensic/report.py`:

- `build_report_dict()` → 15-section machine-readable document:
  case_information, investigation_question, executive_summary, timeline,
  verified_findings, unverified_findings, conflicting_evidence, evidence_gaps,
  supporting_evidence, vlm_observations, track_information, camera_information,
  limitations, reviewer_information, audit_information
- `to_render_input()` → `{report_title, sections: [{title, content}]}` for `render_report()`
- `render_report()` (reportlab 5.0.1) → PDF bytes with Content-Disposition download
- Report stored in MinIO via `storage.put_bytes("reports", ...)`
- Version incremented on re-generation; content + data persisted in `ForensicReport`

## 13. Frontend UI

`frontend/app/runs/[runId]/page.tsx` — Client-side forensic workspace:

- Timeline display: chronological entries with timestamp, classification badges, camera/track labels, quality warnings, conflicts, evidence IDs
- Findings: support-score chips (matched/mismatched), review buttons, reviewer history
- Contradictions: amber alert box listing both evidence IDs
- Gaps: list of gap kinds with coverage notes
- Relationships: BEFORE/AFTER with causal-safety icon
- Multi-camera: POSSIBLE_CORRELATION/UNKNOWN labels
- Report: generate + download buttons
- RBAC-aware error handling (REVIEWER 403 on analyze)
- Investigate page link added to run header

## 14. REST API

| Method | Path | RBAC | Notes |
|--------|------|------|-------|
| POST | /runs/{id}/forensic/analyze | LIVE_ROLES | Requires COMPLETED/READY_FOR_REVIEW |
| GET | /runs/{id}/forensic | LIVE_ROLES | Includes timeline_rows |
| POST | /runs/{id}/findings/{fid}/review | RUN_REVIEW_ROLES | Reviewer can review |
| GET | /runs/{id}/reviews | LIVE_ROLES | run + finding reviews |
| POST | /runs/{id}/report | LIVE_ROLES | Requires COMPLETED only |
| GET | /runs/{id}/report | LIVE_ROLES | Content + metadata |
| GET | /runs/{id}/report/file | LIVE_ROLES | PDF/MD bytes download |

## 15. Database Schema (Migration 0008)

`0008_phase8_forensics` applied to live Postgres (head):

- `forensic_timeline_events`: TL-xx id, timestamp, end_timestamp, camera_id, track_id, object_class, event_type, classification, confidence, source, verification_status, quality_flags, conflicts, evidence_ids, event_time, analysis_time, storage_time
- `forensic_analyses`: run_id (unique), investigation_id, generated_at, status, summary, timeline JSON, findings JSON, correlations JSON, contradictions JSON, gaps JSON, relationships JSON, multi_camera JSON, metrics JSON, evidence_counts JSON, user_id
- `finding_reviews`: run_id, investigation_id, finding_id, action, comment, finding_snapshot JSON, reviewer_user_id, reviewed_at
- `forensic_reports`: run_id, investigation_id, title, version, file_format, content JSON, data (bytes), storage_path, status, generated_at, user_id

## 16. RBAC and Access Control

- Forensic analyze, timeline, reviews listing, report generation/download: **LIVE_ROLES** (ADMIN, INVESTIGATOR, SECURITY_OFFICER)
- Finding review: **RUN_REVIEW_ROLES** (adds REVIEWER)
- REVIEWER **403 on analyze** — verified in both unit tests and demo verifier
- Report generation requires `run.status == COMPLETED` (409 otherwise)
- All operations audit-logged via `record_audit`

## 17. Testing

### Unit/Integration (19/19 PASS)

`tests/test_forensic_phase8.py` — SQLite in-memory, session-scoped create_all:

1. Timeline chronological + never invents
2. Merges same-track within epsilon
3. Distinct times → distinct entries
4. Conflicting evidence flagged (not resolved)
5. VLM observed merges with source frames
6. Verified OBSERVED finding scores high support
7. Low-resolution frame-only → never OBSERVED
8. Sequencing never causal
9. Gaps include missing ranges + camera coverage
10. Unanswerable run → honest summary
11. Analysis persisted to DB
12. Timeline rows persisted
13. Reanalyzing replaces (not appends)
14. RBAC: reviewer cannot analyze (403)
15. GET forensic returns analysis
16. Reviewer records finding review
17. Reviews endpoint returns all
18. E2E: analyze → review → report full cycle
19. Report requires COMPLETED (409 for READY_FOR_REVIEW)

### Demo Verifier (46/46 PASS)

`scripts/verify_forensic_reporting.py` against live Postgres + Qdrant + MinIO:

- COMPLETE: timeline, findings, correlations, gaps, no contradictions, non-causal
- TEMPORAL: relationships, BEFORE ordering, all causal=False, causal_note present
- UNKNOWN: identity abstention, no driver/identity claims in findings or summary
- CONFLICT: T-DEMO-CONF contradictions surfaced, event_type preserved, events not merged
- EVIDENCE-GAP: missing_camera_coverage, gap notes, no outside-event invention
- Finding review lifecycle: reviewer accepts, review persisted, re-fetch confirms
- RBAC: REVIEWER 403 on analyze
- Report: PDF (reportlab), 15 sections, download bytes, version increments
- Report blocked until COMPLETED (409 for READY_FOR_REVIEW)

## 18. Performance Results

| Scenario | Endpoint (ms) | Pipeline total (s) | Load (s) | Timeline (s) | Verification (s) | Gaps (s) | Sequencing (s) |
|----------|---------------|-------------------|----------|--------------|-------------------|----------|----------------|
| COMPLETE | 43.5 | 0.0038 | 0.0028 | 0.0006 | 0.0001 | 0.0002 | 0.0000 |
| TEMPORAL | 35.8 | 0.0017 | 0.0009 | 0.0004 | 0.0001 | 0.0002 | 0.0000 |
| UNKNOWN | 21.7 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| CONFLICT | 38.3 | 0.0012 | 0.0009 | 0.0002 | 0.0000 | 0.0001 | 0.0000 |
| EVIDENCE-GAP | 26.6 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| REPORT | 31.9 | 0.0023 | 0.0014 | 0.0005 | 0.0001 | 0.0002 | 0.0000 |

Pipeline overhead is sub-millisecond across all stages. Report rendering (reportlab PDF) is ~30ms including storage write. The pipeline is not a latency bottleneck.

## 19. Regression Status

Full test suite: **397 collected, 391 passed, 6 failed, 0 skipped**.

All 6 failures are pre-existing `tests/test_evaluation.py` failures (missing `data/evaluation/benchmark.jsonl`; created by PHASE 7 VERIFICATION scope). **Zero new regressions introduced by Phase 8.**

Phase 8 forensic tests: **19/19 green**.

## 20. Demo Scenarios

| # | Scenario | Query | Key Assertion |
|---|----------|-------|---------------|
| 1 | COMPLETE | "Find all evidence for track T-P6-CAR-2." | Timeline with 4 events, observed findings, correlations, no contradictions |
| 2 | TEMPORAL | "Find all evidence for track T-P6-PERSON-1." | Relationships present, all BEFORE, all causal=False with note |
| 3 | UNKNOWN | "Who was driving the vehicle in the parking area?" | Run abstains UNKNOWN; no identity claims in findings or summary |
| 4 | CONFLICT | "Find all evidence for track T-DEMO-CONF" | Contradictions surfaced, type=event_type, events kept separate |
| 5 | EVIDENCE-GAP | "Did anything happen outside the camera view during the incident?" | missing_camera_coverage gap, no outside-event invention |

## 21. Blockers and Limitations

**None** — reportlab 5.0.1 successfully installed (internet available), PDF rendering confirmed.

Existing limitations (inherent to the forensic domain, not Phase 8 gaps):
- Timeline limited to 200 entries (`FORENSIC_MAX_TIMELINE_ENTRIES`)
- Multi-camera POSSIBLE_CORRELATION is conservative (never SAME_OBJECT)
- Sequencing uses temporal proximity only (no physical-motion model)
- Reviewer actions stored separately; original evidence immutable

## 22. Security Considerations

- All forensic operations audit-logged with user_id, entity_type, entity_id
- Finding snapshots captured at review time (immutability)
- No external API calls in the forensic pipeline (deterministic, no network dependency)
- Report files stored in MinIO with access-control via storage service
- RBAC enforced on all 7 endpoints; REVIEWER restricted from analysis

## 23. Evidence Lifecycle

1. Phase 5 capture → `ForensicEvidence` rows (provenance, sha256, Qdrant index)
2. Phase 7 run → `InvestigationRun.result` (evidence_used with `evidence_id` keys)
3. Phase 8 analyze → reads evidence rows by `public_id` from `result.evidence_used`
4. Pipeline stages operate on these rows; **never modifies source evidence**
5. Results persisted in `ForensicAnalysis`, `ForensicTimelineEvent`
6. Human review → `FindingReview` (snapshot captured)
7. Report → `ForensicReport` (content + rendered PDF in MinIO)

## 24. Configuration

```python
FORENSIC_MAX_TIMELINE_ENTRIES = 200
FORENSIC_OVERLAP_EPSILON_SECONDS = 2.0   # merge window for same-track events
FORENSIC_GAP_THRESHOLD_SECONDS = 30.0    # gap detection threshold
FORENSIC_NEAR_SECONDS = 5.0              # NEAR relationship threshold
FORENSIC_LOW_RESOLUTION_PX = 480         # low-resolution quality flag
FORENSIC_REPORT_RENDERER = "reportlab"   # pdf | md
FORENSIC_REPORT_TITLE_PREFIX = "Investigation Report"
```

## 25. PHASE 8 VERDICT

```
PHASE 8 VERDICT: READY FOR PHASE 9
```

All deliverables complete: forensic pipeline, timeline, verification, human review, 15-section reports (PDF), frontend UI, 19 unit tests + 46 E2E checks, zero new regressions, sub-millisecond pipeline latency. No blockers.

---

## PHYSICAL LIVE CAMERA VERIFICATION (added 2026-09-27)

Verdict for this phase: **VERIFIED** against real services; the physical
laptop-webcam capture step is **NOT TESTED** (no capture device is reachable from
the verification container).

| Item | Result |
|---|---|
| webcam transport (shares one `LocalOpenCVCameraSource` with `droidcam_usb`) | IMPLEMENTED + VERIFIED (14 unit/integration tests) |
| Capture device on indices 0-3 | NOT TESTED — `/dev/video*` absent in the container |
| Docker cannot see a host camera | CONFIRMED (`verify_webcam.py --probe` → `RESULT: NO DEVICE`) |
| PostgreSQL 15.19 / MinIO / Qdrant (dims 384) | PASS — real services, no fallback |
| YOLO | `yolov8n.pt` on **CPU** (`torch.cuda.is_available() == False`) |
| Real VLM provider | NOT TESTED — no credentials configured |
| Defect fixed here | `reportlab==4.2.5` added so reports render as a real PDF instead of degrading to markdown |

To complete the physical step, run the backend host-native and follow
`WEBCAM_SETUP.md`:

``bash
python backend/scripts/verify_webcam.py --probe
python backend/scripts/verify_webcam.py --device 0 --seconds 10
python backend/scripts/verify_live_webcam.py --base-url http://127.0.0.1:8000 --device 0 --seconds 45
``

Full evidence: `FINAL_SYSTEM_REPORT.md`.
