"""Demo Investigation Dataset - downloader, hasher, metadata extractor.

Downloads real PUBLIC sample videos used ONLY as clearly-labeled demo media
for the demo investigation workflow. All items are labeled:

    DEMO DATA - NOT REAL FORENSIC EVIDENCE

Sources (no licenses are invented - each entry records its real source and
license as documented by the provider):

* https://github.com/intel-iot-devkit/sample-videos  (CC BY 4.0, Intel IoT
  DevKit; repository archived Sep 2024). Real surveillance-style demo clips
  of vehicles, persons, retail aisles and classrooms.
* https://test-videos.co.uk Big Buck Bunny short clip (movie is CC BY 3.0,
  (c) 2008 Blender Foundation / www.bigbuckbunny.org). Used to exercise the
  "non-permission / cartoon content" robustness scenario.

This script is stdlib-only and idempotent. It must run with the backend as the
working directory so relative data paths resolve under ``data/``:

    python scripts/download_demo_investigation_data.py

Re-running verifies every already-downloaded video against its recorded
sha256 in ``metadata/manifest.json`` and only re-downloads on mismatch.
ffmpeg/ffprobe must be on PATH for metadata + keyframe extraction.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

ROOT_NAME = "demo_investigation"

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ------------------------------------------------------------------ sources

INTEL_LICENSE = {
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_repo": "https://github.com/intel-iot-devkit/sample-videos",
    "attribution": "Intel IoT DevKit sample-videos repository",
}

BBB_LICENSE = {
    "license": "Big Buck Bunny (c) 2008 Blender Foundation, CC BY 3.0",
    "license_url": "https://creativecommons.org/licenses/by/3.0/",
    "source_repo": "https://test-videos.co.uk",
    "attribution": "Big Buck Bunny short clip hosted by test-videos.co.uk",
}

GITHUB_RAW = "https://github.com/intel-iot-devkit/sample-videos/raw/master/"


@dataclass(frozen=True)
class Source:
    demo_id: str
    filename: str
    source_url: str
    license: dict
    scene_archetype: str
    notes: str
    scenario_keys: tuple[str, ...] = ()
    stable_name: str = ""


VIDEO_SOURCES = [
    Source(
        demo_id="DVS-001",
        filename="demo_video_01_parking_cars.mp4",
        source_url=GITHUB_RAW + "car-detection.mp4",
        license=INTEL_LICENSE,
        scene_archetype="parking / vehicle lane with cars (and persons)",
        notes="Intel car-detection sample clip (real footage).",
        scenario_keys=("vehicle_detection", "multi_object_tracking", "object_stopping", "cctv_complete_investigation"),
        stable_name="demo_vehicle_detection.mp4",
    ),
    Source(
        demo_id="DVS-002",
        filename="demo_video_02_street_persons_bikes.mp4",
        source_url=GITHUB_RAW + "person-bicycle-car-detection.mp4",
        license=INTEL_LICENSE,
        scene_archetype="street intersection with persons, bicycles and vehicles",
        notes="Intel person-bicycle-car-detection sample clip (real footage). Primary E2E demo video.",
        scenario_keys=("person_detection", "multi_object_tracking", "object_movement", "temporal_investigation",
                       "multiple_events", "cctv_complete_investigation"),
        stable_name="demo_multi_object_tracking.mp4",
    ),
    Source(
        demo_id="DVS-003",
        filename="demo_video_03_retail_store_aisle.mp4",
        source_url=GITHUB_RAW + "store-aisle-detection.mp4",
        license=INTEL_LICENSE,
        scene_archetype="indoor retail store aisle with customers",
        notes="Intel store-aisle-detection sample clip (real footage).",
        scenario_keys=("person_detection", "object_entry_exit", "object_movement", "crowd_complex_scene"),
        stable_name="demo_crowd_complex_scene.mp4",
    ),
    Source(
        demo_id="DVS-004",
        filename="demo_video_04_public_people.mp4",
        source_url=GITHUB_RAW + "people-detection.mp4",
        license=INTEL_LICENSE,
        scene_archetype="public area with multiple persons walking",
        notes="Intel people-detection sample clip (real footage).",
        scenario_keys=("person_detection", "object_movement", "crowd_complex_scene"),
        stable_name="demo_person_detection.mp4",
    ),
    Source(
        demo_id="DVS-005",
        filename="demo_video_05_archive_classroom.mp4",
        source_url=GITHUB_RAW + "classroom.mp4",
        license=INTEL_LICENSE,
        scene_archetype="indoor classroom with seated persons",
        notes="Intel classroom sample clip (real footage).",
        scenario_keys=("person_detection", "prolonged_presence"),
        stable_name="demo_prolonged_presence.mp4",
    ),
    Source(
        demo_id="DVS-006",
        filename="demo_video_06_cartoon_robustness.mp4",
        source_url=(
            "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/"
            "Big_Buck_Bunny_360_10s_1MB.mp4"
        ),
        license=BBB_LICENSE,
        scene_archetype="animated cartoon content (Big Buck Bunny 10s)",
        notes="SCENARIO: non-permission / cartoon content. Expected person/vehicle "
        "detection counts near zero; recorded honestly in results.",
        scenario_keys=("vlm_scene_understanding", "cartoon_robustness"),
        stable_name="demo_vlm_scene_understanding.mp4",
    ),
    Source(
        demo_id="DVS-007",
        filename="demo_video_07_one_by_one_person_detection.mp4",
        source_url=GITHUB_RAW + "one-by-one-person-detection.mp4",
        license=INTEL_LICENSE,
        scene_archetype="single persons entering the scene one at a time",
        notes="Intel one-by-one-person-detection sample clip (real footage). "
        "Good for entry/exit + person detection scenarios.",
        scenario_keys=("person_detection", "object_entry_exit"),
        stable_name="demo_object_entry_exit.mp4",
    ),
    Source(
        demo_id="DVS-008",
        filename="demo_video_08_worker_zone.mp4",
        source_url=GITHUB_RAW + "worker-zone-detection.mp4",
        license=INTEL_LICENSE,
        scene_archetype="industrial worker zone with persons working",
        notes="Intel worker-zone-detection sample clip (real footage). "
        "Good for prolonged presence near a fixed region.",
        scenario_keys=("person_detection", "prolonged_presence", "object_movement"),
        stable_name="demo_object_stopping.mp4",
    ),
    Source(
        demo_id="DVS-009",
        filename="demo_video_09_face_demographics_walking.mp4",
        source_url=GITHUB_RAW + "face-demographics-walking.mp4",
        license=INTEL_LICENSE,
        scene_archetype="persons walking through a corridor (face demographics demo)",
        notes="Intel face-demographics-walking sample clip (real footage). "
        "Multiple persons moving; crowd/complex scene.",
        scenario_keys=("person_detection", "object_movement", "crowd_complex_scene"),
        stable_name="demo_object_movement.mp4",
    ),
    Source(
        demo_id="DVS-010",
        filename="demo_video_10_face_demographics_walking_pause.mp4",
        source_url=GITHUB_RAW + "face-demographics-walking-and-pause.mp4",
        license=INTEL_LICENSE,
        scene_archetype="persons walking then pausing (face demographics demo)",
        notes="Intel face-demographics-walking-and-pause sample clip (real footage). "
        "Persons stop briefly — good for stopping + prolonged presence + entry/exit.",
        scenario_keys=("person_detection", "object_stopping", "prolonged_presence", "object_entry_exit"),
        stable_name="demo_temporal_investigation.mp4",
    ),
]

# keyframes to extract per video (fraction of duration), for image/evidence demos
KEYFRAME_FRACTIONS = {
    "DVS-001": (0.25, 0.70),
    "DVS-002": (0.25, 0.70),
    "DVS-003": (0.30, 0.60),
    "DVS-004": (0.30, 0.60),
    "DVS-005": (0.40, 0.60),
    "DVS-007": (0.30, 0.60),
    "DVS-008": (0.30, 0.60),
    "DVS-009": (0.30, 0.60),
    "DVS-010": (0.30, 0.60),
}

FIXTURE_SPECS = [
    {
        "filename": "empty_static_scene.mp4",
        "kind": "negative-fixture:empty-scene",
        "notes": "SYNTHETIC test fixture (ffmpeg black color source) - NOT real "
        "footage. Exercises 'empty scene' handling: expected zero detections/events.",
    },
    {
        "filename": "not_a_video.mp4",
        "kind": "negative-fixture:invalid-video",
        "notes": "SYNTHETIC test fixture: text bytes with a .mp4 extension. "
        "Upload/processing must fail gracefully (job FAILED, no crash).",
    },
]

DISCLAIMER = (
    "DEMO DATA - NOT REAL FORENSIC EVIDENCE. Every item in this dataset is a "
    "public sample clip used only to demo the AI Forensic Investigation System. "
    "Nothing here depicts real incidents, real suspects, real victims or "
    "admissible evidence. Do not use demo data in any real investigation."
)

# The 12 demo scenarios requested for the E2E dataset. Each stable_name is the
# canonical scenario identifier; demo_ids lists every video backing it.
SCENARIO_CATALOG = [
    {"key": "person_detection", "stable_name": "demo_person_detection.mp4",
     "demo_ids": ["DVS-004", "DVS-002", "DVS-007", "DVS-009", "DVS-010"]},
    {"key": "vehicle_detection", "stable_name": "demo_vehicle_detection.mp4",
     "demo_ids": ["DVS-001"]},
    {"key": "multi_object_tracking", "stable_name": "demo_multi_object_tracking.mp4",
     "demo_ids": ["DVS-002", "DVS-001"]},
    {"key": "object_entry_exit", "stable_name": "demo_object_entry_exit.mp4",
     "demo_ids": ["DVS-007", "DVS-003", "DVS-010"]},
    {"key": "object_movement", "stable_name": "demo_object_movement.mp4",
     "demo_ids": ["DVS-009", "DVS-002", "DVS-003", "DVS-010"]},
    {"key": "object_stopping", "stable_name": "demo_object_stopping.mp4",
     "demo_ids": ["DVS-008", "DVS-010", "DVS-001"]},
    {"key": "prolonged_presence", "stable_name": "demo_prolonged_presence.mp4",
     "demo_ids": ["DVS-005", "DVS-008", "DVS-010"]},
    {"key": "multiple_events", "stable_name": "demo_multiple_events.mp4",
     "demo_ids": ["DVS-002", "DVS-010"]},
    {"key": "temporal_investigation", "stable_name": "demo_temporal_investigation.mp4",
     "demo_ids": ["DVS-010", "DVS-002"]},
    {"key": "vlm_scene_understanding", "stable_name": "demo_vlm_scene_understanding.mp4",
     "demo_ids": ["DVS-006", "DVS-002"]},
    {"key": "crowd_complex_scene", "stable_name": "demo_crowd_complex_scene.mp4",
     "demo_ids": ["DVS-003", "DVS-004", "DVS-009"]},
    {"key": "cctv_complete_investigation", "stable_name": "demo_cctv_complete_investigation.mp4",
     "demo_ids": ["DVS-001", "DVS-002"]},
]


# ------------------------------------------------------------------- helpers


def _mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ffprobe_meta(path: str) -> dict:
    if not _which("ffprobe"):
        return {}
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        data = json.loads(proc.stdout)
    except Exception:
        return {}
    meta = {"duration_seconds": 0.0, "width": 0, "height": 0, "fps": 0.0, "codec": ""}
    fmt = data.get("format", {})
    try:
        meta["duration_seconds"] = round(float(fmt.get("duration") or 0.0), 3)
    except (TypeError, ValueError):
        pass
    for stream in data.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        try:
            meta["width"] = int(stream.get("width") or 0)
            meta["height"] = int(stream.get("height") or 0)
        except (TypeError, ValueError):
            pass
        meta["codec"] = stream.get("codec_name") or ""
        fps_str = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/0"
        try:
            num, den = fps_str.split("/")
            meta["fps"] = round(float(num) / float(den), 3) if float(den) else 0.0
        except (ValueError, ZeroDivisionError):
            meta["fps"] = 0.0
        break
    return meta


def _which(name: str) -> bool:
    from shutil import which

    return which(name) is not None


def download(url: str, dest: str) -> None:
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Forensic-Demo-Dataset/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)


def run_ffmpeg(args: list[str], timeout: int = 120) -> None:
    cmd = ["ffmpeg", "-y", *args]
    subprocess.run(cmd, capture_output=True, check=True, timeout=timeout)


# --------------------------------------------------------------------- build


def _load_manifest(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _recorded_hashes(manifest: dict | None) -> dict:
    out = {}
    if manifest:
        for entry in manifest.get("videos", []):
            out[entry["demo_id"]] = entry.get("sha256")
    return out


def _thumbnail_entry(root: str, demo_id: str) -> dict | None:
    """Return a manifest entry for ``thumbnails/<demo_id>.jpg`` if it exists."""
    path = os.path.join(root, "thumbnails", f"{demo_id}.jpg")
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None
    return {
        "demo_id": demo_id,
        "filename": f"{demo_id}.jpg",
        "path": f"thumbnails/{demo_id}.jpg",
        "sha256": sha256_file(path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", help="absolute dataset root (default: <cwd>/data)")
    args = parser.parse_args()

    data_root = args.data_dir or os.path.join(BACKEND_DIR, "data")
    root = os.path.join(data_root, ROOT_NAME)
    videos_dir = os.path.join(root, "videos")
    images_dir = os.path.join(root, "images")
    fixtures_dir = os.path.join(root, "videos", "fixtures")
    meta_dir = os.path.join(root, "metadata")
    for d in (videos_dir, images_dir, fixtures_dir, meta_dir):
        _mkdir(d)

    manifest_path = os.path.join(meta_dir, "manifest.json")
    prior = _load_manifest(manifest_path)
    known = _recorded_hashes(prior)

    videos_out = []
    failures = []

    for src in VIDEO_SOURCES:
        dest = os.path.join(videos_dir, src.filename)
        recorded = known.get(src.demo_id)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            h = sha256_file(dest)
            if not recorded or h == recorded:
                print(f"  keep {src.demo_id} {src.filename} (ok)")
            else:
                print(f"  sha256 mismatch {src.demo_id}; re-downloading")
                try:
                    download(src.source_url, dest)
                except Exception as exc:  # noqa: BLE001
                    print(f"  download failed {src.demo_id}: {exc}")
                    failures.append(src.demo_id)
                    continue
        else:
            try:
                download(src.source_url, dest)
            except Exception as exc:  # noqa: BLE001
                print(f"  download failed {src.demo_id}: {exc}")
                failures.append(src.demo_id)
                continue

        if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
            print(f"  empty after download {src.demo_id}; skipping")
            failures.append(src.demo_id)
            continue

        meta = ffprobe_meta(dest)
        entry = {
            "demo_id": src.demo_id,
            "filename": src.filename,
            "path": f"videos/{src.filename}",
            "source_url": src.source_url,
            "source_repo": src.license["source_repo"],
            "license": src.license["license"],
            "license_url": src.license["license_url"],
            "attribution": src.license["attribution"],
            "scene_archetype": src.scene_archetype,
            "notes": src.notes,
            "stable_name": src.stable_name,
            "scenario_keys": list(src.scenario_keys),
            "sha256": sha256_file(dest),
            "size_bytes": os.path.getsize(dest),
            **{k: meta.get(k) for k in ("duration_seconds", "width", "height", "fps", "codec")},
        }
        videos_out.append(entry)
        print(
            f"  ok {src.demo_id} {src.filename} "
            f"({entry['width']}x{entry['height']} {entry['duration_seconds']}s "
            f"sha256={entry['sha256'][:12]}…)"
        )

    # keyframes
    keyframes_out = []
    if _which("ffmpeg"):
        for demo_id, fractions in KEYFRAME_FRACTIONS.items():
            src = next((s for s in VIDEO_SOURCES if s.demo_id == demo_id), None)
            if not src:
                continue
            meta = next((v for v in videos_out if v["demo_id"] == demo_id), None)
            if not meta or not meta.get("duration_seconds"):
                continue
            duration = float(meta["duration_seconds"])
            for i, frac in enumerate(fractions, start=1):
                ts = duration * frac
                out_name = f"keyframe_{demo_id}_{i}.jpg"
                out_path = os.path.join(images_dir, out_name)
                try:
                    run_ffmpeg([
                        "-ss", f"{ts:.3f}", "-i", os.path.join(videos_dir, src.filename),
                        "-frames:v", "1", "-q:v", "2", out_path,
                    ])
                    keyframes_out.append({
                        "filename": out_name,
                        "path": f"images/{out_name}",
                        "source_demo_id": demo_id,
                        "timestamp_seconds": round(ts, 3),
                        "sha256": sha256_file(out_path),
                    })
                    print(f"  keyframe {out_name} @ {ts:.1f}s")
                except Exception as exc:  # noqa: BLE001
                    print(f"  keyframe {out_name} failed: {exc}")
    else:
        print("  ffmpeg not found; skipping keyframe extraction")

    # negative fixtures
    fixtures_out = []
    empty_path = os.path.join(fixtures_dir, "empty_static_scene.mp4")
    if _which("ffmpeg") and not os.path.isfile(empty_path):
        try:
            run_ffmpeg([
                "-f", "lavfi", "-i", "color=c=black:s=640x360:d=3:r=25",
                "-pix_fmt", "yuv420p", empty_path,
            ])
        except Exception as exc:  # noqa: BLE001
            print(f"  empty-scene fixture failed: {exc}")
    if os.path.isfile(empty_path) and os.path.getsize(empty_path) > 0:
        fixtures_out.append({
            "filename": "empty_static_scene.mp4",
            "path": "videos/fixtures/empty_static_scene.mp4",
            "kind": "negative-fixture:empty-scene",
            "sha256": sha256_file(empty_path),
            "notes": FIXTURE_SPECS[0]["notes"],
        })

    not_a_video = os.path.join(fixtures_dir, "not_a_video.mp4")
    with open(not_a_video, "w", encoding="utf-8") as fh:
        fh.write("this is not a video - negative fixture for graceful failure testing\n")
    fixtures_out.append({
        "filename": "not_a_video.mp4",
        "path": "videos/fixtures/not_a_video.mp4",
        "kind": "negative-fixture:invalid-video",
        "sha256": sha256_file(not_a_video),
        "notes": "SYNTHETIC fixture: text bytes with a .mp4 extension.",
    })

    manifest = {
        "schema_version": 1,
        "dataset": "DEMO INVESTIGATION DATASET",
        "declared_kind": "demo",
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "scenario_catalog": SCENARIO_CATALOG,
        "videos": videos_out,
        "keyframes": keyframes_out,
        # Drop missing thumbnails instead of writing nulls: a null entry makes
        # every manifest consumer (API + verifiers) fail on `.get()`.
        "thumbnails": [t for t in (_thumbnail_entry(root, v["demo_id"]) for v in videos_out)
                       if t is not None],
        "fixtures": fixtures_out,
    }
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    with open(os.path.join(root, "fixtures_notes.txt"), "w", encoding="utf-8") as fh:
        fh.write("see metadata/manifest.json and README.md for fixture descriptions\n")

    print(f"\nmanifest written to {manifest_path} ({len(videos_out)} videos, "
          f"{len(keyframes_out)} keyframes, {len(fixtures_out)} fixtures)")
    if failures:
        print(f"MISSING/FAILED videos: {failures}")
        sys.exit(1)


if __name__ == "__main__":
    main()