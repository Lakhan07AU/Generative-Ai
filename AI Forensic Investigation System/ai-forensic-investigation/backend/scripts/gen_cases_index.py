"""Build ``data/demo_investigation/cases.json`` from the real downloaded dataset.

The demo case index (``cases.json``) is a *derived index*: it maps each licensed
demo clip (DVS-001..010) to its already-downloaded scenario, expected-events and
expected-observations files. ``scripts/gen_demo_scenarios.py`` extends an
existing ``cases.json``; this script builds the index from scratch when the file
is absent from a fresh checkout.

Nothing here invents forensic content. Every field is taken from files that were
downloaded and verified by ``download_demo_investigation_data.py``:

  * video_file                  <- metadata/manifest.json
  * expected_events_file        <- expected_events/<demo_id>.json  (must exist)
  * expected_observations_file  <- scenarios/<scenario_id>.json -> expected_observations/
  * investigation_queries_file  <- scenarios/<scenario_id>.json -> investigation_queries/
  * title / description / query <- scenarios/<scenario_id>.json (title, purpose)

Usage:
    python scripts/gen_cases_index.py [--root data/demo_investigation]
"""

from __future__ import annotations

import argparse
import json
import os

DISCLAIMER = "DEMO DATA - NOT REAL FORENSIC EVIDENCE"


def _load(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def build(root: str) -> list[dict]:
    manifest = _load(os.path.join(root, "metadata", "manifest.json"))
    scen_dir = os.path.join(root, "scenarios")
    scenarios = [_load(os.path.join(scen_dir, name)) for name in sorted(os.listdir(scen_dir))]

    # demo_id -> scenario whose "videos" entry claims that clip.
    demo_to_scenario: dict[str, dict] = {}
    for scn in scenarios:
        for v in scn.get("videos") or []:
            demo_to_scenario.setdefault(v["demo_id"], scn)

    cases: list[dict] = []
    for video in manifest["videos"]:
        demo_id = video["demo_id"]
        scn = demo_to_scenario.get(demo_id)
        if scn is None:
            raise SystemExit(f"no scenario record references {demo_id}")
        scenario_id = scn["scenario_id"]
        events_rel = f"expected_events/{demo_id.lower()}.json"
        obs_rel = f"expected_observations/{scenario_id}.json"
        query_rel = f"investigation_queries/{scenario_id}.json"
        for rel in (events_rel, obs_rel, query_rel):
            if not os.path.isfile(os.path.join(root, rel)):
                raise SystemExit(f"{demo_id}: expected dataset file missing: {rel}")
        cases.append({
            "case_id": f"CASE-DEMO-{len(cases) + 1:03d}",
            "title": f"{scn.get('title', scenario_id)} ({demo_id})",
            "description": scn.get("purpose", ""),
            "demo_id": demo_id,
            "video_file": video["filename"],
            "video_path": video["path"],
            "query": (scn.get("purpose") or f"Describe what happened in {video['filename']}."),
            "expected_events_file": events_rel,
            "expected_observations_file": obs_rel,
            "investigation_queries_file": query_rel,
            "scenario_ids": [scenario_id],
            "labels": scn.get("labels") or [],
            "status": "OPEN",
            "priority": "normal",
            "notes": f"{DISCLAIMER}. Public sample clip; not real evidence.",
        })
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the demo cases.json index")
    parser.add_argument("--root", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "demo_investigation"))
    parser.add_argument("--force", action="store_true", help="overwrite an existing cases.json")
    args = parser.parse_args()

    out = os.path.join(args.root, "cases.json")
    if os.path.isfile(out) and not args.force:
        print(f"cases.json already present ({out}); use --force to rebuild")
        return 0

    cases = build(args.root)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(cases, fh, indent=2, ensure_ascii=False)
    print(f"cases.json: {len(cases)} cases written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
