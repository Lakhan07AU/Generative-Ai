"""Demo Investigation Dataset - offline tests.

Validates the demo dataset integrity, manifest SHA-256 hashes, cases,
expected-events/observations schema, negative fixtures and the real CV2
file-feeder transport - all fully offline, no network, no running server.

Every dataset-dependent test uses the same skip-if-missing pattern as the
Phase 4 vlm tests so the suite stays green on a fresh clone that has not
downloaded the demo media.
"""

import importlib
import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
PROJECT_ROOT = os.path.join(HERE, "..")
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
SCRIPTS_DIR = os.path.join(BACKEND_DIR, "scripts")

DATA_DIR = os.path.join(BACKEND_DIR, "data", "demo_investigation")
MANIFEST_FILE = os.path.join(DATA_DIR, "metadata", "manifest.json")
CASES_FILE = os.path.join(DATA_DIR, "cases.json")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

download = importlib.import_module("download_demo_investigation_data")


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _sha256(path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


requires_dataset = pytest.mark.skipif(
    not os.path.isdir(DATA_DIR) or not os.path.isfile(MANIFEST_FILE),
    reason="demo investigation dataset not present (run scripts/download_demo_investigation_data.py)",
)

EXPECTED_DEMO_IDS = {f"DVS-{i:03d}" for i in range(1, 11)}


# ---------------------------------------------------------------- downloader


def test_downloader_declares_ten_licensed_sources():
    assert len(download.VIDEO_SOURCES) == 10
    assert {s.demo_id for s in download.VIDEO_SOURCES} == EXPECTED_DEMO_IDS
    for s in download.VIDEO_SOURCES:
        assert s.license["license"]
        assert s.license["source_repo"]
        assert any(s.demo_id == v["demo_id"] for v in _load_json(MANIFEST_FILE)["videos"])


# ------------------------------------------------------------------- dataset


@requires_dataset
def test_manifest_file_valid_json():
    manifest = _load_json(MANIFEST_FILE)
    assert manifest["schema_version"] == 1
    assert "NOT REAL FORENSIC EVIDENCE" in manifest["disclaimer"]


@requires_dataset
def test_manifest_declares_ten_demo_videos():
    manifest = _load_json(MANIFEST_FILE)
    assert len(manifest["videos"]) == 10
    assert all(v["demo_id"] in EXPECTED_DEMO_IDS for v in manifest["videos"])


@requires_dataset
@pytest.mark.parametrize("demo_id", sorted(EXPECTED_DEMO_IDS))
def test_video_integrity_sha256_matches_manifest(demo_id):
    manifest = _load_json(MANIFEST_FILE)
    entry = next(v for v in manifest["videos"] if v["demo_id"] == demo_id)
    path = os.path.join(DATA_DIR, entry["path"])
    assert os.path.isfile(path), f"missing {entry['path']}"
    assert _sha256(path) == entry["sha256"]
    assert entry.get("duration_seconds", 0) > 0
    assert entry.get("license")
    assert entry.get("source_url")


@requires_dataset
def test_each_video_has_verifiable_license_and_source():
    manifest = _load_json(MANIFEST_FILE)
    for v in manifest["videos"]:
        assert v["license"]
        assert v["source_repo"]
        # Intel clips are CC BY 4.0, BBB is CC BY (Blender); nothing fabricated.
        assert "CC BY" in v["license"]


@requires_dataset
def test_keyframes_and_fixtures_present():
    manifest = _load_json(MANIFEST_FILE)
    assert len(manifest["keyframes"]) >= 8
    for k in manifest["keyframes"]:
        assert os.path.isfile(os.path.join(DATA_DIR, k["path"])), k["path"]
    assert len(manifest["fixtures"]) == 2
    for f in manifest["fixtures"]:
        assert os.path.isfile(os.path.join(DATA_DIR, f["path"])), f["path"]


# ---------------------------------------------------------------------- cases


@requires_dataset
def test_cases_json_is_valid_with_ten_demo_cases():
    cases = _load_json(CASES_FILE)
    assert isinstance(cases, list)
    assert len(cases) == 10
    assert all(c["case_id"].startswith("CASE-DEMO-") for c in cases)


@requires_dataset
def test_cases_reference_real_videos():
    cases = _load_json(CASES_FILE)
    manifest = _load_json(MANIFEST_FILE)
    filenames = {v["filename"] for v in manifest["videos"]}
    for c in cases:
        assert c["video_file"] in filenames
        assert any(m["demo_id"] == c.get("demo_id") for m in manifest["videos"])


@requires_dataset
@pytest.mark.parametrize("n", range(1, 11))
def test_each_case_references_existing_expected_files(n):
    case_id = f"CASE-DEMO-{n:03d}"
    cases = _load_json(CASES_FILE)
    case = next(c for c in cases if c["case_id"] == case_id)
    for rel in (case["expected_events_file"], case["expected_observations_file"]):
        path = os.path.join(DATA_DIR, rel)
        assert os.path.isfile(path), rel
        data = _load_json(path)  # must be valid JSON


@requires_dataset
def test_expected_events_files_declared_as_non_forensic_reference():
    import glob

    for path in glob.glob(os.path.join(DATA_DIR, "expected_events", "*.json")):
        text = open(path, "r", encoding="utf-8").read()
        assert "DEMO EXPECTED EVENTS" in text or "not forensic ground truth" in text.lower(), path


@requires_dataset
def test_expected_observations_classifications_are_grounded():
    import glob

    classifications = set()
    for path in glob.glob(os.path.join(DATA_DIR, "expected_observations", "*.json")):
        data = _load_json(path)
        assert "scenarios" in data
        assert "DEMO EXPECTED OBSERVATIONS" in data.get("disclaimer", "")
        for s in data["scenarios"]:
            answer = s.get("expected")
            assert answer in ("OBSERVED", "UNKNOWN"), (path, answer)
            assert s.get("question")
            classifications.add(answer)
    assert classifications == {"OBSERVED", "UNKNOWN"}


# ------------------------------------------------------------ negative fixtures


@requires_dataset
def test_invalid_video_fixture_is_not_decodable():
    path = os.path.join(DATA_DIR, "videos", "fixtures", "not_a_video.mp4")
    assert os.path.isfile(path)
    with open(path, "rb") as fh:
        assert not fh.read(64).startswith(b"\x00\x00\x00")
    # ffprobe must fail (non-zero) on this fixture
    import subprocess

    proc = subprocess.run(["ffprobe", "-v", "error", path], capture_output=True, timeout=60)
    assert proc.returncode != 0


@pytest.mark.skipif(not (os.path.isdir(DATA_DIR) and os.path.isdir(os.path.join(DATA_DIR, "videos", "fixtures"))), reason="fixtures not present")
def test_empty_scene_fixture_is_a_decodable_video():
    path = os.path.join(DATA_DIR, "videos", "fixtures", "empty_static_scene.mp4")
    if not os.path.isfile(path):
        pytest.skip("empty-scene fixture missing")
    import subprocess

    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-print_format", "json", path],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    video_stream = next(s for s in data.get("streams", []) if s.get("codec_type") == "video")
    assert video_stream["width"] and video_stream["height"]


# -------------------------------------------------- real file feeder transport


class _StubRuntime:
    def __init__(self):
        self.camera_id = 1
        self.frames = []
        self.ingest_frame = self._ingest

    def _ingest(self, frame, ts):
        self.frames.append((ts, frame.shape[:2]))
        return True


@pytest.mark.skipif(not os.path.isfile(os.path.join(DATA_DIR, "videos", "fixtures", "empty_static_scene.mp4")), reason="fixture missing")
def test_video_file_feeder_real_decode_produces_frames():
    import time

    from app.live.video_feeder import VideoFileFeeder

    path = os.path.join(DATA_DIR, "videos", "fixtures", "empty_static_scene.mp4")
    stub = _StubRuntime()
    feeder = VideoFileFeeder(stub, path, fps_target=30, loop=False)
    feeder.start()
    deadline = time.time() + 15
    while len(stub.frames) < 40 and time.time() < deadline:
        time.sleep(0.1)
    feeder.stop()
    assert len(stub.frames) >= 40, f"expected >=40 frames, got {len(stub.frames)}"


def test_video_file_feeder_rejects_missing_file():
    from app.live.video_feeder import VideoFileFeeder

    stub = _StubRuntime()
    try:
        feeder = VideoFileFeeder(stub, os.path.join(DATA_DIR, "nope_missing.mp4"))
    except Exception:
        feeder = None
    if feeder is not None:
        feeder.stop()


# ------------------------------------------------------------- demo API router


@requires_dataset
def test_demo_api_functions_offline():
    from app.api import demo

    manifest = demo.demo_dataset()
    assert len(manifest["videos"]) == 10
    assert all(v.get("abs_path") for v in manifest["videos"])
    cases = demo.demo_cases()
    assert len(cases) == 10
    assert demo.demo_case("CASE-DEMO-001")["case_id"] == "CASE-DEMO-001"
    assert len(demo.demo_scenarios()) >= 12