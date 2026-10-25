# Phase 4 Report — VLM / Multimodal Grounding Layer & Internet Test Data

Date: 2026-09-11
Scope: Phase 4 of the AI Forensic Investigation System — (a) a real-time live VLM observation layer over the Phase 2/3 detection+tracking pipeline, (b) VLM grounding checks that enforce evidence-tied observations and explicit UNKNOWN / INSUFFICIENT_EVIDENCE abstention (no identity/intent inference), (c) a small **internet-sourced visual test dataset** (`data/vlm_test/`) kept strictly separate from real forensic evidence, and (d) an offline validation harness + tests.

---

## 1. Implemented functionality

| Component | Description | Location |
|---|---|---|
| Grounding evaluator | Pure-text offline evaluation of a structured VLM observation against supplied evidence: coverage of expected observable facts, fabrication detection (statements sharing no content token with the evidence vocabulary), prohibited-theme detection (identity/name/intent/… with stem-tolerant matching), and explicit UNKNOWN / INSUFFICIENT_EVIDENCE abstention checks | `backend/app/validation/vlm_check.py` |
| Grounding semantics | Normal cases require coverage > 0 AND no unsupported AND no prohibited claims; UNKNOWN cases PASS only when the model produced an abstention, and FAIL if it asserts a theme the frames cannot support (even with plausible wording); `INSUFFICIENT_EVIDENCE` treated as abstention | `backend/app/validation/vlm_check.py` |
| Test-fixture downloader | Explicit curated `MANIFEST` (14 items) only — no crawling, no URL arguments; HTTP 2xx + magic-byte (JPEG / ISO-BMFF MP4) + size validation; SHA-256 persisted; reuses verified cache (`--check` offline re-verify); per-item fail-safe; never executes downloads; writes only under `data/vlm_test/` | `backend/scripts/download_vlm_test_data.py` |
| Test dataset | 10 public JPEGs (Pexels, 800px: streets/parking/retail, people+vehicles) + 4 public MP4s (Sintel & Big Buck Bunny open-movie samples CC-BY 3.0, 10s 360p clip, generic 640x360 clip); per-item metadata (source URL/site/page, retrieval date, original/local filename, media type, dimensions, duration, license, size, SHA-256) | `data/vlm_test/` + `metadata.json` |
| Validation harness | 15 offline-groundable cases: 10 image (understanding, objects, spatial), 2 UNKNOWN abstention (pedestrian identity, truck intent), 3 video (multi-frame/temporal, movement); writes reviewed results | `backend/scripts/vlm_validate.py` |
| Tests | 23 new tests: deterministic grounding semantics, downloader safety invariants (no URL input, no subprocess/exec, path containment), manifest/metadata consistency, fixture hashes, offline validation output | `tests/test_vlm_validation.py` |

Phase 4 requirements honored: dataset is INTERNET TEST DATA and never treated as, mixed with, or sourced from real forensic evidence; downloader never crawls; tests + app run fully offline (fixtures are optional); VLM observations are forced against provenance (input → VLM → structured observation → expected observable facts → result); UNKNOWN / INSUFFICIENT_EVIDENCE cases exercise uncertainty and hallucination resistance without identity or intent inference.

## 2. Internet test data — composition

| Kind | Count | Sources | License |
|---|---|---|---|
| Images (JPEG) | 10 | Pexels (images.pexels.com) | Pexels License (free to use, no attribution required) |
| Videos (MP4) | 4 | W3C media samples, test-videos.co.uk, filesamples.com | Blender open movies CC-BY 3.0; generic sample clip |

Total 14 fixtures, ~18.0 MB on disk. Dimensions/durations recorded in `metadata.json`
(e.g. Sintel 854x480 ~52.2 s, BBB trailer 853x480 ~32.4 s, BBB 360p 10 s, sample 640x360 ~13.3 s; images 800px JPEG).
All per-item `source_url`/`source_page`/`license`/`retrieval_date`/`original_filename`/`local_filename`/`media_type`/resolution/duration/`sha256` are machine-readable. None of the fixtures are surveillance footage; they exercise generic public scenes with multiple objects/people for pipeline validation only.

## 3. Internet test data — reproducibility & safety

- `backend/scripts/download_vlm_test_data.py`: only `MANIFEST` URLs are ever contacted (verified reachable at authoring time); accepts no URL argument; magic bytes ignore URL extensions; per-item size bounds + 200 MB hard cap; SHA-256 persisted; previously verified fixtures are skipped (no duplicate downloads); a single failure never aborts the run; downloaded bytes are never executed and nothing is copied out of `data/vlm_test/`.
- Offline: `python scripts/download_vlm_test_data.py --check` re-verifies the cache with zero network access — **PASSED for all 14 items** (see §6).
- `data/vlm_test/README.md` and `metadata.json` `dataset.classification = "INTERNET_TEST_DATA"` carry the explicit disclaimer that this data must never be used to ground conclusions about real cases.

## 4. Internet test data — VLM validation results (harness)

`backend/scripts/vlm_validate.py` runs 15 cases; each record logs input (`sha256`, `source_url`, `local_filename`), the VLM observation, and the grounding verdict(s) to `data/vlm_test/validation_results.json`.

| Case group | Cases | Result with `simulation` provider |
|---|---|---|
| Image understanding / objects / spatial (10) | parking, street people+cars, crosswalk, supermarket, interior, sidewalk, traffic intersection, groceries, NYC street, crowded street | **FAIL — without a real vision model no observation can be grounded** (see §9; simulations correctly abstain, and a normal case needs actual content) |
| UNKNOWN abstention (2) | pedestrian identity, truck intent | **PASS — model abstained, asserted nothing prohibited** |
| Video temporal / movement (3) | BBB 10s ordering, Sintel motion, sample clip | **FAIL — same honest caveat as images** |

The 2 PASS cases prove the abstention path end-to-end; the 13 FAIL cases are expected with the default `simulation` provider and are precisely why the harness reports results honestly rather than pretending a pipeline that does not see visuals is validated.

## 5. New tests (`tests/test_vlm_validation.py` — 23, all PASS)

| Group | Tests | Verifies |
|---|---|---|
| Grounding (normal) | grounded observation passes; hallucinated statement flagged; metadata-context evidence; UNKNOWN ≠ grounding; partial coverage + missing facts; wording invariance; malformed classification coercion | Deterministic evaluator semantics |
| UNKNOWN cases | pass-when-abstaining; fail-when-guessing-identity; fail-when-not-abstaining; fail-on-fabricated-observed-fact; JSON-serialisable verdict | No identity/intent inference; abstention required |
| Downloader safety | curated bounded manifest (10 img + 4 vid); required metadata fields; **no URL argument / no crawling**; **no subprocess/os.system/eval/exec**; **writes only under `data/vlm_test/`**; validation cases reference only manifest fixtures; UNKNOWN cases present | Fail-safe, offline, evidence-separated |
| Fixture consistency (skipped when data absent) | metadata.json matches manifest + verified; on-disk SHA-256 match; offline validation results file shape | Reproducible, hashed dataset |

All 23 tests are fully offline; fixture-dependent tests self-skip on a fresh clone.

## 6. Offline verification run (recorded)

```
$ python scripts/download_vlm_test_data.py --check    (from backend/)
[ok] vlm_img_parking_trucks … [ok] vlm_img_crowded_street   (10 images)
[ok] vlm_vid_sintel_trailer [ok] vlm_vid_bunny_trailer
[ok] vlm_vid_bbb_360_10s [ok] vlm_vid_sample_640x360
Offline check PASSED for all manifest items.
```

`python scripts/download_vlm_test_data.py` (no args) also runs and writes `metadata.json` with `retrieval_date` and rev-verified SHA-256s for every item.

## 7. Full-suite result

`python -m pytest`: **260 passed, 6 skipped, 6 failed** in ~141 s.

* The 6 failures are `tests/test_evaluation.py`, pre-existing and unrelated to Phase 4: they require `data/evaluation/benchmark.jsonl`, which is absent from this checkout (documented in Phases 1–3).
* New Phase 4 module: `tests/test_vlm_validation.py` 23/23 PASS.

## 8. Files added or modified

- **New:** `backend/app/validation/vlm_check.py`, `backend/scripts/download_vlm_test_data.py`, `backend/scripts/vlm_validate.py`, `tests/test_vlm_validation.py`, `data/vlm_test/README.md`, `data/vlm_test/metadata.json`, `data/vlm_test/validation_results.json` (generated), `data/vlm_test/images/*` (10), `data/vlm_test/videos/*` (4).
- No Alembic migration; no new runtime dependencies (download/validation use stdlib + the existing vision stack; cv2 used opportunistically for video metadata).

## 9. Honest limitations / NOT TESTED

- **Real VLM provider run: NOT EXECUTED.** `LLM_PROVIDER`/`VLM_PROVIDER` default to `simulation` on this host, so image/video content cases correctly FAIL — proving the harness reports truthfully instead of laundering a non-vision pipeline into a green light. Running with a real OpenAI-compatible VLM (`VLM_ENABLED=true` + provider/model configured) is the intended next step; `gnd_*` abstention cases pass even in simulation.
- Expected-observable facts are author-time human ground truths; real-frame verification of every fixture is a lighter ongoing curation task.
- `ffmpeg`/`ffprobe` not installed (carried): video metadata relies on cv2; uploads to COMPLETED remain limited (carried from Phases 1–3).
- MinIO / Qdrant offline and CPU-only host: unchanged environmental facts.

## 10. Delta vs Phase 3 report

Added: `app/validation/` grounding evaluator; internet test-data downloader + dataset (`data/vlm_test/`, 14 fixtures, hashed metadata); offline VLM validation harness (15 cases); 23 new tests; README + this report subsection. Caveats carried forward unchanged: missing `benchmark.jsonl` (6 pre-existing eval failures), no ffmpeg, MinIO/Qdrant offline, CPU-only, no physical device / real-network E2E. New honest caveat: real-VLM grounding runs not executed on this host (can be run against any OpenAI-compatible VLM endpoint).

## 11. Verdict

### DELIVERED — INTERNET TEST DATA + OFFLINE VLM GROUNDING VALIDATION

The internet-sourced (strictly non-evidence) VLM test dataset is reproducible, hashed, licensed, offline-verifiable and clearly segregated; the grounding evaluator enforces evidence-tied observations and mandated abstention on UNKNOWN cases (identity/intent inference rejected); the harness and 23 tests run 100% offline. Remaining work is connecting a real VLM provider so the content-grounding cases turn green — a configuration exercise, with the honest simulation-mode failures already in `validation_results.json`.