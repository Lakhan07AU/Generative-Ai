"""Generate demo dataset supporting artifacts: scenarios/, investigation_queries/,
extended expected_events/, expected_observations/ and the updated cases.json.

All expectations are honest validation conditions, NOT forensic ground truth.
Runs from the backend directory:  python scripts/gen_demo_scenarios.py
"""

from __future__ import annotations

import json
import os

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "demo_investigation")

MANIFEST_PATH = os.path.join(ROOT, "metadata", "manifest.json")
CASES_PATH = os.path.join(ROOT, "cases.json")
EVENTS_DIR = os.path.join(ROOT, "expected_events")
OBS_DIR = os.path.join(ROOT, "expected_observations")
SCEN_DIR = os.path.join(ROOT, "scenarios")
QUERY_DIR = os.path.join(ROOT, "investigation_queries")

DISCLAIMER = "DEMO DATA - NOT REAL FORENSIC EVIDENCE"

# ----------------------------------------------------------------------------
# Scenario definitions: key -> (stable_name, title, purpose, demo_ids,
#                              event expectations, vlm notes)
# ----------------------------------------------------------------------------

SCENARIOS = [
    {
        "key": "person_detection",
        "stable_name": "demo_person_detection.mp4",
        "title": "Person Detection",
        "purpose": "Verify YOLO person detection and per-person tracking count across public scenes.",
        "demo_ids": ["DVS-004", "DVS-002", "DVS-007", "DVS-009", "DVS-010"],
        "labels": ["person"],
        "event_expectation": "person_present >= 1 when YOLO available",
    },
    {
        "key": "vehicle_detection",
        "stable_name": "demo_vehicle_detection.mp4",
        "title": "Vehicle Detection",
        "purpose": "Verify car/vehicle detection in a parking lot with moving and stationary vehicles.",
        "demo_ids": ["DVS-001"],
        "labels": ["car", "truck", "motorcycle"],
        "event_expectation": "car detections >= 1; no expectation of persons",
    },
    {
        "key": "multi_object_tracking",
        "stable_name": "demo_multi_object_tracking.mp4",
        "title": "Multi-Object Tracking",
        "purpose": "Verify simultaneous tracking of multiple persons, bicycles and vehicles at a street intersection.",
        "demo_ids": ["DVS-002", "DVS-001"],
        "labels": ["person", "bicycle", "car"],
        "event_expectation": "tracked objects (person/car/bicycle) >= 2",
    },
    {
        "key": "object_entry_exit",
        "stable_name": "demo_object_entry_exit.mp4",
        "title": "Object Entry / Exit",
        "purpose": "Verify entry/exit events when objects cross the scene boundary (one-by-one and aisle clips).",
        "demo_ids": ["DVS-007", "DVS-003", "DVS-010"],
        "labels": ["person"],
        "event_expectation": "entry/exit style events (object entered/exited) observed when tracking runs",
    },
    {
        "key": "object_movement",
        "stable_name": "demo_object_movement.mp4",
        "title": "Object Movement",
        "purpose": "Verify movement metrics (velocity, distance) for moving persons in corridors and streets.",
        "demo_ids": ["DVS-009", "DVS-002", "DVS-003", "DVS-010"],
        "labels": ["person"],
        "event_expectation": "moved events or positive distance_traveled_px on >=2 tracks",
    },
    {
        "key": "object_stopping",
        "stable_name": "demo_object_stopping.mp4",
        "title": "Object Stopping",
        "purpose": "Verify stoppage detection for persons that pause in a worker zone or walking-pause clip.",
        "demo_ids": ["DVS-008", "DVS-010", "DVS-001"],
        "labels": ["person"],
        "event_expectation": "stationary/stopped state observed on at least one track",
    },
    {
        "key": "prolonged_presence",
        "stable_name": "demo_prolonged_presence.mp4",
        "title": "Prolonged Presence",
        "purpose": "Verify sustained presence (remaining in scene for an extended window) in classroom/worker scenes.",
        "demo_ids": ["DVS-005", "DVS-008", "DVS-010"],
        "labels": ["person"],
        "event_expectation": "person tracks present across most of the clip duration",
    },
    {
        "key": "multiple_events",
        "stable_name": "demo_multiple_events.mp4",
        "title": "Multiple Events",
        "purpose": "Verify more than one event type (presence + motion + dense scenes) per investigation window.",
        "demo_ids": ["DVS-002", "DVS-010"],
        "labels": ["person", "bicycle", "car"],
        "event_expectation": "2 or more distinct event types recorded",
    },
    {
        "key": "temporal_investigation",
        "stable_name": "demo_temporal_investigation.mp4",
        "title": "Temporal Investigation",
        "purpose": "Verify time-ordered queries (when did X happen, before/after Y) over indexed evidence.",
        "demo_ids": ["DVS-010", "DVS-002"],
        "labels": ["person"],
        "event_expectation": "evidence carries timestamp_seconds allowing before/after SQL",
    },
    {
        "key": "vlm_scene_understanding",
        "stable_name": "demo_vlm_scene_understanding.mp4",
        "title": "VLM Scene Understanding",
        "purpose": "Verify VLM scene observation and honest abstention (cartoon clip -> UNKNOWN for forensic claims).",
        "demo_ids": ["DVS-006", "DVS-002"],
        "labels": [],
        "event_expectation": "VLM observation recorded; cartoon scene yields UNKNOWN/abstain answers",
    },
    {
        "key": "crowd_complex_scene",
        "stable_name": "demo_crowd_complex_scene.mp4",
        "title": "Crowd / Complex Scene",
        "purpose": "Verify dense multi-person scenes (retail aisle, public plaza) are handled without crash and measured honestly.",
        "demo_ids": ["DVS-003", "DVS-004", "DVS-009"],
        "labels": ["person"],
        "event_expectation": "person detections >= 1 (count is honest, may be high density)",
    },
    {
        "key": "cctv_complete_investigation",
        "stable_name": "demo_cctv_complete_investigation.mp4",
        "title": "Fixed CCTV Complete Investigation",
        "purpose": "VERIFY the full pipeline on one fully-investigated CCTV-style clip: ingestion -> detection -> tracking -> events -> VLM -> evidence -> RAG -> agent answer.",
        "demo_ids": ["DVS-001", "DVS-002"],
        "labels": ["person", "car"],
        "event_expectation": "complete investigation possible: evidence indexed, RAG query answered, grounded answer produced",
    },
]


def scenario_id(key: str, index: int) -> str:
    return f"SCN-{index + 1:02d}-{key}"


# ----------------------------------------------------------------------------
# Investigation queries per scenario (ungrounded / grounded / UNKNOWN)
# ----------------------------------------------------------------------------

def queries_for(sc: dict) -> dict:
    key = sc["key"]
    ungrounded = [
        "What objects are visible in this footage?",
        "How many distinct objects were tracked across the clip?",
        "What types of activities appear to be taking place?",
    ]
    grounded = [
        "When did the first person appear on camera?",
        "Did any vehicle pass through the scene?",
        "How long did the tracked object remain in the scene?",
    ]
    unknown = [
        "What is the identity of the person in this footage?",
        "Was a crime committed in this footage? (do not infer intent or guilt)",
        "What was the license plate number of any vehicle?",
        "What was the subject thinking or intending?",
    ]
    # Tailor grounding per scenario: mild variation to keep scenarios distinct.
    if key == "vehicle_detection":
        grounded = ["What vehicles are visible in this footage?", "When did vehicles appear in the scene?"]
        unknown = ["What is the vehicle registration number?", "Who owns the vehicles?"]
    elif key == "cartoon_robustness":
        grounded = ["Describe the scene type visible in this clip (if any)."]
        unknown = ["Are any real persons present in this cartoon clip?", "Is this real surveillance footage?"]
    elif key == "vlm_scene_understanding":
        grounded = ["Describe the scene visible in this clip."]
        unknown = ["Is this footage real or synthetic/animations?", "Can any identity be attached to subjects?"]
    elif key == "cctv_complete_investigation":
        grounded = [
            "Summarize the sequence of events visible in this CCTV clip.",
            "When did the first object enter the scene and the last one leave?",
        ]
        unknown = [
            "Who exactly is the subject recorded here?",
            "What motivated the people in this footage?",
        ]
    return {
        "scenario_id": scenario_id(key, 0),
        "key": key,
        "queries": {
            "ungrounded": ungrounded,
            "grounded": grounded,
            "unknown": unknown,
        },
    }


# ----------------------------------------------------------------------------
# expected_events for a video (honest conditions; offline pipeline model)
# ----------------------------------------------------------------------------

def event_expectations(video_id: str) -> dict:
    return {
        "video_id": video_id,
        "disclaimer": DISCLAIMER,
        "model": "offline-pipeline (detection -> per-frame clips)",
        "conditions": [
            "if YOLO unavailable: detection_count == 0 and event_count == 0 (honest, recorded)",
            "detections/events are validation ranges, NOT forensic ground truth",
        ],
        "expected": [],
    }


def observation_expectations(scene: dict) -> dict:
    scenarios = [
        {"question": q, "expected": "OBSERVED"} for q in scene["observed_questions"]
    ] + [
        {"question": q, "expected": "UNKNOWN"} for q in scene["unknown_questions"]
    ]
    return {
        "scenario_id": scene["scenario_id"],
        "scenario_key": scene["key"],
        "kind": "DEMO EXPECTED OBSERVATIONS",
        "disclaimer": (
            f"DEMO EXPECTED OBSERVATIONS — reference labels for a grounded VLM, "
            f"not fabricated forensic truth. {DISCLAIMER}."
        ),
        "questions_observed": scene["observed_questions"],
        "questions_unknown": scene["unknown_questions"],
        "scenarios": scenarios,
        "model": "simulation VLM provider returns UNKNOWN/abstain (honest, acceptable)",
    }


# ----------------------------------------------------------------------------
# Build everything
# ----------------------------------------------------------------------------

def _relink_existing_cases(cases: list, video_by_id: dict, scenario_records: list) -> None:
    """Attach scenario_ids + query/observation links to the pre-existing cases."""
    for case in cases:
        demo_id = case.get("demo_id")
        if not demo_id or case.get("scenario_ids"):
            continue
        dv = video_by_id.get(demo_id, {})
        stable = dv.get("stable_name") or ""
        scenario = next((s for s in scenario_records if s["stable_name"] == stable), None) or next(
            (s for s in scenario_records if s["key"] == (dv.get("scenario_keys") or [""])[0]), None
        )
        if scenario:
            case["scenario_ids"] = [scenario["scenario_id"]]
            case["expected_observations_file"] = f"expected_observations/{scenario['scenario_id']}.json"
            case["investigation_queries_file"] = f"investigation_queries/{scenario['scenario_id']}.json"
        case["expected_events_file"] = f"expected_events/{demo_id.lower()}.json"
    with open(CASES_PATH, "w", encoding="utf-8") as fh:
        json.dump(cases, fh, indent=2, ensure_ascii=False)


def main() -> None:
    manifest = json.load(open(MANIFEST_PATH, encoding="utf-8"))
    video_by_id = {v["demo_id"]: v for v in manifest["videos"]}

    os.makedirs(SCEN_DIR, exist_ok=True)
    os.makedirs(QUERY_DIR, exist_ok=True)
    os.makedirs(EVENTS_DIR, exist_ok=True)
    os.makedirs(OBS_DIR, exist_ok=True)

    scenario_records = []
    for i, sc in enumerate(SCENARIOS):
        scid = scenario_id(sc["key"], i)
        stable = sc["stable_name"]
        # map demo_ids to filenames
        videos = [
            {"demo_id": d, "filename": video_by_id[d]["filename"],
             "stable_name": video_by_id[d].get("stable_name", "")}
            for d in sc["demo_ids"] if d in video_by_id
        ]
        observed_q = [
            "Is there a person visible in this scene? [person scenes]",
            "What objects does the YOLO layer report in this clip?",
        ]
        if sc["key"] == "vehicle_detection":
            observed_q = ["Are vehicles visible in this scene?", "What vehicle types does the detection layer report?"]
        unknown_q = [
            "What is the identity of any subject in this footage?",
            "Is any subject committing an offense? (inferring intent is forbidden)",
        ]
        if sc["key"] == "vlm_scene_understanding":
            unknown_q = ["Is this real surveillance footage or synthetic/animations?", "Can any identity be attached to subjects?"]

        scenario = {
            "scenario_id": scid,
            "key": sc["key"],
            "stable_name": stable,
            "title": sc["title"],
            "purpose": sc["purpose"],
            "labels": sc["labels"],
            "event_expectation": sc["event_expectation"],
            "videos": videos,
            "observed_questions": observed_q,
            "unknown_questions": unknown_q,
            "disclaimer": DISCLAIMER,
        }
        scenario_records.append(scenario)

        # scenario JSON
        with open(os.path.join(SCEN_DIR, f"{scid}.json"), "w", encoding="utf-8") as fh:
            json.dump(scenario, fh, indent=2, ensure_ascii=False)

        # investigation queries JSON
        with open(os.path.join(QUERY_DIR, f"{scid}.json"), "w", encoding="utf-8") as fh:
            json.dump(queries_for(sc), fh, indent=2, ensure_ascii=False)

        # expected_observations per scenario
        with open(os.path.join(OBS_DIR, f"{scid}.json"), "w", encoding="utf-8") as fh:
            json.dump(observation_expectations(scenario), fh, indent=2, ensure_ascii=False)

        # expected_events per backing video
        for v in videos:
            events_path = os.path.join(EVENTS_DIR, f"{v['demo_id'].lower()}.json")
            if not os.path.exists(events_path):
                data = event_expectations(v["demo_id"])
                data["labels"] = sc["labels"]
                data["event_expectation"] = sc["event_expectation"]
                data["scenario_keys"] = [sc["key"]]
                with open(events_path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, ensure_ascii=False)

    # Update cases.json: keep existing 5 cases, add one per new video 007-010.
    cases = json.load(open(CASES_PATH, encoding="utf-8"))
    existing = {c["case_id"] for c in cases}
    new_case_specs = [
        {
            "case_id": "CASE-DEMO-006",
            "title": "Corridor One-by-One Person Entry",
            "description": "Single persons entering a corridor one at a time; entry/exit and person detection scenario.",
            "demo_id": "DVS-007",
            "video_file": "demo_video_07_one_by_one_person_detection.mp4",
            "query": "When did each person enter the corridor scene and how long did each remain?",
            "priority": "normal",
        },
        {
            "case_id": "CASE-DEMO-007",
            "title": "Worker Zone Activity Review",
            "description": "Workers active in an industrial zone; stoppage and prolonged-presence scenario.",
            "demo_id": "DVS-008",
            "video_file": "demo_video_08_worker_zone.mp4",
            "query": "Did any worker remain stationary in the zone for a prolonged period?",
            "priority": "normal",
        },
        {
            "case_id": "CASE-DEMO-008",
            "title": "Corridor Movement Flow",
            "description": "Persons walking along a corridor; movement and crowd-flow scenario.",
            "demo_id": "DVS-009",
            "video_file": "demo_video_09_face_demographics_walking.mp4",
            "query": "How many persons moved through the corridor and in which direction?",
            "priority": "normal",
        },
        {
            "case_id": "CASE-DEMO-009",
            "title": "Walking with Pauses Temporal Review",
            "description": "Persons walking then pausing; stopping, temporal and entry/exit scenario.",
            "demo_id": "DVS-010",
            "video_file": "demo_video_10_face_demographics_walking_pause.mp4",
            "query": "At what times did persons stop moving within the scene?",
            "priority": "normal",
        },
        {
            "case_id": "CASE-DEMO-010",
            "title": "Cartoon Non-Permission Awareness",
            "description": "Animated cartoon clip to exercise 'non-permission/cartoon content' handling: VLM must abstain and person/vehicle detection is expected near zero.",
            "demo_id": "DVS-006",
            "video_file": "demo_video_06_cartoon_robustness.mp4",
            "query": "Is any real person or vehicle present in this cartoon clip?",
            "priority": "normal",
        },
    ]
    for spec in new_case_specs:
        # find scenario id whose stable_name matches this video's primary scenario
        dv = video_by_id.get(spec["demo_id"], {})
        stable = dv.get("stable_name") or ""
        scenario = next((s for s in scenario_records if s["stable_name"] == stable), None) or next(
            (s for s in scenario_records if s["key"] == (dv.get("scenario_keys") or [""])[0]), None
        )
        spec["expected_observations_file"] = f"expected_observations/{scenario['scenario_id']}.json" if scenario else None
        spec["investigation_queries_file"] = f"investigation_queries/{scenario['scenario_id']}.json" if scenario else None
        spec["expected_events_file"] = f"expected_events/{spec['demo_id'].lower()}.json"
        if scenario:
            spec["scenario_ids"] = [scenario["scenario_id"]]
        spec["status"] = "OPEN"
        spec["notes"] = f"{DISCLAIMER}. Public sample clip; not real evidence."

        existing_idx = next((i for i, c in enumerate(cases) if c["case_id"] == spec["case_id"]), None)
        if existing_idx is not None:
            # update in place so re-runs keep the correct scenario links
            merged = {**cases[existing_idx], **spec}
            cases[existing_idx] = merged
        else:
            cases.append(spec)

    with open(CASES_PATH, "w", encoding="utf-8") as fh:
        json.dump(cases, fh, indent=2, ensure_ascii=False)

    # Enrich the pre-existing cases (CASE-DEMO-001..005) with scenario links too.
    _relink_existing_cases(cases, video_by_id, scenario_records)

    # summary
    print(f"scenarios: {len(scenario_records)} written to {SCEN_DIR}")
    print(f"investigation queries: written to {QUERY_DIR}")
    print(f"expected_observations: written to {OBS_DIR}")
    print(f"cases.json: {len(cases)} cases")
    print("expected_events present:", sorted(os.listdir(EVENTS_DIR)))


if __name__ == "__main__":
    main()