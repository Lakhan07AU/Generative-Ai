"""Phase 4 - offline VLM validation harness over internet test fixtures.

Runs the application's real observation pipeline (``provider.vision_observe_frames``
plus the copy-safe ``app.vlm.preprocess.encode_frames`` preprocessing) against
the curated ``data/vlm_test/`` fixtures, and evaluates each structured
observation for grounding in the supplied visual evidence using
``app.validation.vlm_check``.

* FULLY OFFLINE - no network access; uses only local fixtures.
* Uses a REAL VLM when one is configured (``LLM_PROVIDER``/``VLM_PROVIDER``);
  otherwise the deterministic simulation provider is used and outcome quality
  is reported but honestly labelled as simulation.
* Never requires the VLM to reproduce exact wording - only that statements are
  grounded in the supplied evidence and that the system abstains
  (UNKNOWN / INSUFFICIENT_EVIDENCE) where the frames cannot support a claim.

Usage (from ``backend/``):

    python scripts/vlm_validate.py                  # run all cases, write results
    python scripts/vlm_validate.py --only gnd_pedestrian_identity_unknown
    python scripts/vlm_validate.py --strict         # exit non-zero on any FAIL
    python scripts/vlm_validate.py --limit 5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from types import SimpleNamespace
from typing import Any

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.dirname(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

DATA_DIR = os.path.join(BASE_DIR, "data", "vlm_test")
METADATA_FILE = os.path.join(DATA_DIR, "metadata.json")
RESULTS_FILE = os.path.join(DATA_DIR, "validation_results.json")

from app.vlm.preprocess import encode_frames  # noqa: E402
from app.validation.vlm_check import evaluate_grounding, evaluate_unknown_case  # noqa: E402

MAX_FRAMES = 3


@dataclass
class Case:
    """A single VLM validation case authored against a fixture.

    ``expected_facts`` are the observable facts a human verifier established by
    looking at the fixture (ground truth - exact wording is NOT required in the
    observation). ``prohibited_themes`` are topics the observation must never
    assert from the frames (identity, intent, names, …). When ``expect_unknown``
    is set, the CORRECT answer is UNKNOWN / INSUFFICIENT_EVIDENCE.
    """

    case_id: str
    fixture_id: str
    kind: str  # "image" | "video"
    expected_facts: list[str]
    prohibited_themes: list[str] = field(default_factory=list)
    expect_unknown: bool = False
    note: str = ""


# ---------------------------------------------------------------------------
# Authored validation cases (tied to data/vlm_test fixtures)
# ---------------------------------------------------------------------------

TEST_CASES: list[Case] = [
    # ---- Images: people / vehicles / streets / parking / retail -------------
    Case(
        "img_parking_trucks", "vlm_img_parking_trucks", "image",
        ["parking lot", "truck", "vehicles", "outdoor", "daytime"],
        ["identity", "name", "steal", "theft", "intent", "weapon"],
        note="Vehicle fleet in an open parking area (multiple objects).",
    ),
    Case(
        "img_street_people_cars", "vlm_img_street_people_cars", "image",
        ["pedestrians", "street", "parked car", "trees", "city"],
        ["identity", "name", "robbery", "intent"],
        note="Pedestrians and parked cars on a city street.",
    ),
    Case(
        "img_parking_crosswalk", "vlm_img_parking_crosswalk", "image",
        ["parking lot", "crosswalk", "traffic cones", "pavement markings", "aerial"],
        ["identity", "name", "accident", "crash"],
        note="High-angle parking area with markings and cones.",
    ),
    Case(
        "img_supermarket_aisle", "vlm_img_supermarket_aisle", "image",
        ["supermarket", "aisle", "shelves", "people", "shopping", "indoor"],
        ["shoplift", "identity", "name", "intent"],
        note="Indoor retail: people shopping in an aisle.",
    ),
    Case(
        "img_supermarket_interior", "vlm_img_supermarket_interior", "image",
        ["supermarket", "interior", "aisles", "shelves", "checkout", "indoor"],
        ["shoplift", "identity", "name"],
        note="Indoor retail store interior (no specific people asserted).",
    ),
    Case(
        "img_sidewalk_buildings", "vlm_img_sidewalk_buildings", "image",
        ["sidewalk", "buildings", "people", "walking", "street"],
        ["identity", "name", "intent"],
        note="Pedestrians on a sidewalk between buildings.",
    ),
    Case(
        "img_city_street_traffic", "vlm_img_city_street_traffic", "image",
        ["pedestrians", "traffic lights", "intersection", "crosswalk", "city"],
        ["identity", "name", "shoplift", "intent"],
        note="Busy intersection with pedestrians crossing at lights.",
    ),
    Case(
        "img_family_groceries", "vlm_img_family_groceries", "image",
        ["supermarket", "fruit", "aisle", "shopping", "people"],
        ["identity", "name", "shoplift"],
        note="People selecting fruit in a supermarket (multiple objects).",
    ),
    Case(
        "img_nyc_street", "vlm_img_nyc_street", "image",
        ["city street", "pedestrians", "buildings", "traffic lights", "daytime"],
        ["identity", "name", "intent", "theft"],
        note="Dense daytime city street scene.",
    ),
    Case(
        "img_crowded_street", "vlm_img_crowded_street", "image",
        ["city street", "people", "walking", "buildings"],
        ["identity", "name", "confrontation", "intent"],
        note="Crowded street with many people walking.",
    ),
    # ---- Grounding / abstention cases (correct answer UNKNOWN) --------------
    Case(
        "gnd_pedestrian_identity_unknown", "vlm_img_city_street_traffic", "image",
        ["pedestrians", "traffic lights", "city"],
        ["name", "identity", "gender", "age", "shoplift"],
        expect_unknown=True,
        note="'Is this pedestrian a shoplifter?' cannot be answered - must be UNKNOWN.",
    ),
    Case(
        "gnd_truck_intent_unknown", "vlm_img_parking_trucks", "image",
        ["parking lot", "truck"],
        ["steal", "theft", "intent", "break", "keys"],
        expect_unknown=True,
        note="'Did the driver intend to steal this truck?' cannot be inferred from stills.",
    ),
    # ---- Videos: multi-frame analysis + temporal ordering -------------------
    Case(
        "vid_bbb_temporal_ordering", "vlm_vid_bbb_360_10s", "video",
        ["outdoor environment", "characters", "movement"],
        ["identity", "name", "intent"],
        note="10s clip: 3 ordered keyframes, characters move through the scene (temporal ordering).",
    ),
    Case(
        "vid_sintel_motion", "vlm_vid_sintel_trailer", "video",
        ["characters", "movement", "visual content"],
        ["identity", "name", "intent"],
        note="Open-movie trailer: 3 ordered keyframes with object/people movement.",
    ),
    Case(
        "vid_sample_single_scene", "vlm_vid_sample_640x360", "video",
        ["video content", "visual content", "movement"],
        ["identity", "name", "intent"],
        note="Generic sample clip: 3 ordered keyframes for temporal analysis.",
    ),
]


# ---------------------------------------------------------------------------
# Fixture provenance + frame preparation (offline)
# ---------------------------------------------------------------------------


def _load_metadata() -> dict[str, Any]:
    if not os.path.exists(METADATA_FILE):
        raise SystemExit(f"metadata.json not found at {METADATA_FILE} - run scripts/download_vlm_test_data.py first")
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {it["id"]: it for it in data.get("items", [])}


def _fixture_provenance(records: dict[str, Any], fixture_id: str) -> dict[str, Any]:
    rec = records.get(fixture_id) or {}
    return {
        "fixture_id": fixture_id,
        "local_filename": rec.get("local_filename"),
        "source_url": rec.get("source_url"),
        "source_site": rec.get("source_site"),
        "retrieval_date": rec.get("retrieval_date"),
        "sha256": rec.get("sha256"),
        "media_type": rec.get("media_type"),
        "width": rec.get("width"),
        "height": rec.get("height"),
        "duration_seconds": rec.get("duration_seconds"),
    }


def _prepare_image_entries(path: str) -> list[SimpleNamespace]:
    import cv2

    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cv2 could not decode image: {path}")
    return [SimpleNamespace(sequence=0, timestamp=0.0, frame=img)]


def _prepare_video_entries(path: str) -> list[SimpleNamespace]:
    import cv2

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"cv2 could not open video: {path}")
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        duration = total / fps if fps > 0 else 0.0
        entries: list[SimpleNamespace] = []
        seq = 0
        for i in range(1, MAX_FRAMES + 1):
            t = duration * i / (MAX_FRAMES + 1)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if ok:
                entries.append(SimpleNamespace(sequence=seq, timestamp=t, frame=frame))
                seq += 1
        return entries
    finally:
        cap.release()


def _prepare(path: str, kind: str) -> list[dict[str, Any]]:
    entries = _prepare_image_entries(path) if kind == "image" else _prepare_video_entries(path)
    prepared, dropped = encode_frames(entries, max_side=1280, jpeg_quality=80, max_bytes=512 * 1024)
    frames = [
        {
            "data": pf.data,
            "frame_id": pf.frame_id,
            "sequence": pf.sequence,
            "timestamp": pf.timestamp,
            "width": pf.width,
            "height": pf.height,
        }
        for pf in prepared
    ]
    return frames, dropped


# ---------------------------------------------------------------------------
# Observation + evaluation
# ---------------------------------------------------------------------------


def _observe(frames: list[dict[str, Any]], fixture_id: str) -> dict[str, Any]:
    from app.ai import provider

    context = {
        "camera_id": "vlm_test",
        "camera_name": "internet test fixture",
        "session_id": fixture_id,
        "source_frames": [f"fixture:{fixture_id}#seq{fr['sequence']}" for fr in frames],
        "detections": [],
        "active_tracks": [],
    }
    if frames:
        context["window_start"] = min(fr["timestamp"] for fr in frames)
        context["window_end"] = max(fr["timestamp"] for fr in frames)
    return provider.vision_observe_frames(frames, context)


def _evaluate(observation: dict[str, Any], case: Case, fixture_desc: str) -> dict[str, Any]:
    context_tokens = [fixture_desc]
    if case.expect_unknown:
        return evaluate_unknown_case(
            observation,
            prohibited_themes=case.prohibited_themes,
            expected_facts=case.expected_facts,
            evidence_context=context_tokens,
        )
    return evaluate_grounding(
        observation,
        expected_facts=case.expected_facts,
        evidence_context=context_tokens,
        prohibited_themes=case.prohibited_themes,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_cases(only: list[str] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    from app.ai import provider

    records = _load_metadata()
    cases = [c for c in TEST_CASES if not only or c.case_id in only]
    if limit:
        cases = cases[:limit]

    results: list[dict[str, Any]] = []
    for case in cases:
        rec = records.get(case.fixture_id)
        entry = {
            "case_id": case.case_id,
            "kind": case.kind,
            "input": _fixture_provenance(records, case.fixture_id),
            "expected": {
                "facts": case.expected_facts,
                "prohibited_themes": case.prohibited_themes,
                "expect_unknown": case.expect_unknown,
            },
            "error": None,
        }
        if not rec or not rec.get("local_filename"):
            entry.update({"error": f"fixture {case.fixture_id} not found in metadata.json", "result": "SKIP"})
            results.append(entry)
            continue
        sub = "images" if case.kind == "image" else "videos"
        path = os.path.join(DATA_DIR, sub, rec["local_filename"])
        if not os.path.exists(path):
            entry.update({"error": f"fixture file missing locally: {path}", "result": "SKIP"})
            results.append(entry)
            continue

        entry["input"]["source_path"] = path
        try:
            frames, dropped = _prepare(path, case.kind)
            if not frames:
                raise ValueError("no frames could be prepared for the fixture")
            observation = _observe(frames, case.fixture_id)
            verdict = _evaluate(observation, case, rec.get("description") or case.note)
            result = "PASS" if verdict["grounded"] else "FAIL"
            entry.update(
                {
                    "n_frames": len(frames),
                    "dropped_frames": dropped,
                    "observation": observation,
                    "verdict": verdict,
                    "result": result,
                }
            )
        except Exception as exc:  # noqa: BLE001 - report the failure, keep going
            entry.update({"error": f"{type(exc).__name__}: {exc}", "result": "ERROR"})
        results.append(entry)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline VLM validation over data/vlm_test fixtures.")
    parser.add_argument("--out", default=RESULTS_FILE, help="JSON results file path")
    parser.add_argument("--only", action="append", default=None, help="run only this case_id (repeatable)")
    parser.add_argument("--limit", type=int, default=None, help="run at most N cases")
    parser.add_argument("--strict", action="store_true", help="exit non-zero when any case FAILS")
    args = parser.parse_args(argv)

    results = run_cases(only=args.only, limit=args.limit)

    provider_mode = "simulation"
    try:
        from app.ai import provider as p

        provider_mode = "live" if p.available() else "simulation"
    except Exception:  # noqa: BLE001
        pass

    summary: dict[str, Any] = {"PASS": 0, "FAIL": 0, "SKIP": 0, "ERROR": 0}
    for r in results:
        summary[r["result"]] = summary.get(r["result"], 0) + 1

    payload = {
        "dataset": "vlm_test",
        "classification": "INTERNET_TEST_DATA",
        "disclaimer": "INTERNET TEST DATA - not genuine forensic evidence. Never mixed with evidence storage.",
        "provider_mode": provider_mode,
        "ran_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cases": results,
        "summary": summary,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"\n{'case_id':34s} {'result':7s} provider={provider_mode}")
    print("-" * 60)
    for r in results:
        print(f"{r['case_id']:34s} {r['result']:7s} {(r.get('error') or '')}")
    print(f"\nSummary: {summary}")
    print(f"Results: {args.out}")

    if args.strict and summary.get("FAIL", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())