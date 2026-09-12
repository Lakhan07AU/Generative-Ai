"""Phase 4 - tests for the internet VLM test-data pipeline and grounding checks.

Covers:
* the offline grounding evaluator (``app.validation.vlm_check``) - deterministic,
  no network, no fixtures required;
* the download script's safety invariants (explicit manifest only, magic-byte +
  size validation, SHA-256, no dynamic URL input, no subprocess/exec of
  downloads, writes only under ``data/vlm_test/``);
* fixture/metadata consistency checks (skipped when the fixtures are absent so
  the suite stays green fully offline / on a fresh clone).

The core application must never depend on the internet: the fixtures are
OPTIONAL test data.
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
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "vlm_test")
METADATA_FILE = os.path.join(DATA_DIR, "metadata.json")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from app.validation import vlm_check  # noqa: E402
from app.validation.vlm_check import (  # noqa: E402
    evaluate_grounding,
    evaluate_unknown_case,
    content_tokens,
)

download = importlib.import_module("download_vlm_test_data")
validate = importlib.import_module("vlm_validate")


# ---------------------------------------------------------------------------
# Grounding evaluator: grounded (normal) cases
# ---------------------------------------------------------------------------


def _obs(statements, summary="summary"):
    return {
        "summary": summary,
        "statements": [
            {"statement": s, "classification": c, "confidence": 0.8, "basis": []}
            for s, c in statements
        ],
        "notes": [],
        "model": "test",
    }


def test_grounded_observation_passes():
    obs = _obs(
        [("pedestrians cross the street at the traffic light", "OBSERVED"),
         ("parked cars line the side of the road", "OBSERVED")]
    )
    verdict = evaluate_grounding(
        obs, expected_facts=["pedestrians", "traffic light", "parked cars", "street"]
    )
    assert verdict["grounded"] is True
    assert verdict["unsupported_statements"] == []
    assert verdict["prohibited_claims"] == []
    assert verdict["coverage"] >= 0.75


def test_hallucinated_statement_is_flagged():
    obs = _obs(
        [("pedestrians walk near parked cars", "OBSERVED"),
         ("a person holds a handgun", "OBSERVED")]
    )
    verdict = evaluate_grounding(
        obs, expected_facts=["pedestrians", "parked cars", "street"],
        evidence_context=["city street daytime"],
    )
    assert verdict["grounded"] is False
    assert len(verdict["unsupported_statements"]) == 1
    assert "handgun" in verdict["unsupported_statements"][0]
    assert any("fabrication" in n for n in verdict["notes"])


def test_statement_supported_by_context_metadata_is_not_flagged():
    # "truck" is provided by known detection metadata (evidence context) even
    # though the expected-fact list omits it.
    obs = _obs([("a truck is parked outdoor", "OBSERVED")])
    verdict = evaluate_grounding(
        obs,
        expected_facts=["outdoor"],
        evidence_context=["detection:truck", "session:cam1"],
    )
    assert verdict["grounded"] is True
    assert verdict["unsupported_statements"] == []


def test_unknown_classification_does_not_count_as_grounding():
    obs = _obs([("No objects could be verified in the frame", "UNKNOWN")])
    verdict = evaluate_grounding(obs, expected_facts=["pedestrians"])
    assert verdict["abstained"] is True
    assert verdict["grounded"] is False  # abstention is NOT grounding for normal cases
    assert verdict["coverage"] == 0.0


def test_partial_coverage_reports_missing_facts():
    obs = _obs([("pedestrians are visible", "OBSERVED")])
    verdict = evaluate_grounding(obs, expected_facts=["pedestrians", "parking lot", "truck"])
    # Token-based coverage: "pedestrians" covers 1 of 4 content tokens
    # (pedestrians / parking / lot / truck).
    assert verdict["coverage"] == 0.25
    assert "parking lot" in verdict["missing_facts"]
    assert "truck" in verdict["missing_facts"]


def test_exact_wording_not_required():
    # Wording differs but content tokens still overlap -> grounded.
    obs = _obs([("people are walking near the parked cars", "OBSERVED")])
    verdict = evaluate_grounding(obs, expected_facts=["people walking", "parked cars"])
    assert verdict["grounded"] is True


def test_malformed_classification_coerced_to_unknown():
    obs = {
        "summary": "s",
        "statements": [{"statement": "wat?", "classification": "MAYBE"}],
        "notes": [],
        "model": "test",
    }
    verdict = evaluate_grounding(obs, expected_facts=["people"])
    # Coerced to UNKNOWN -> abstained, not grounded.
    assert verdict["abstained"] is True
    assert verdict["grounded"] is False


# ---------------------------------------------------------------------------
# Grounding evaluator: UNKNOWN / INSUFFICIENT_EVIDENCE cases
# ---------------------------------------------------------------------------


def test_unknown_case_pass_when_abstaining():
    obs = _obs(
        [("A pedestrian is visible near the traffic light", "OBSERVED"),
         ("Whether this pedestrian is a shoplifter cannot be determined", "UNKNOWN")]
    )
    verdict = evaluate_unknown_case(
        obs,
        prohibited_themes=["identity", "name", "gender", "shoplift"],
        expected_facts=["pedestrians", "traffic light"],
    )
    assert verdict["grounded"] is True
    assert verdict["abstained"] is True
    assert verdict["prohibited_claims"] == []


def test_unknown_case_fails_when_guessing_identity():
    obs = _obs([("The man appears to be a shoplifter", "OBSERVED")])
    verdict = evaluate_unknown_case(
        obs, prohibited_themes=["shoplift", "identity", "name", "intent"]
    )
    assert verdict["grounded"] is False
    assert len(verdict["prohibited_claims"]) == 1
    assert any("identity/intent" in n for n in verdict["notes"])


def test_unknown_case_fails_when_not_abstaining():
    obs = _obs([("The truck driver intends to steal the vehicle", "INFERRED")])
    verdict = evaluate_unknown_case(
        obs, prohibited_themes=["steal", "intent", "theft"], expected_facts=["truck"]
    )
    assert verdict["grounded"] is False
    assert any("did not abstain" in n for n in verdict["notes"])


def test_unknown_case_fails_on_fabricated_observed_fact():
    obs = _obs(
        [("The driver has broken into the truck", "OBSERVED"),
         ("Cannot determine", "UNKNOWN")]
    )
    verdict = evaluate_unknown_case(
        obs, prohibited_themes=["steal", "break", "intent"], expected_facts=["parking lot", "truck"]
    )
    assert verdict["grounded"] is False
    assert len(verdict["prohibited_claims"]) == 1


def test_verdict_is_json_serialisable():
    obs = _obs([("pedestrians cross the street", "OBSERVED")])
    verdict = evaluate_grounding(obs, expected_facts=["pedestrians", "street"])
    json.dumps(verdict)  # must not raise


# ---------------------------------------------------------------------------
# content_tokens helper
# ---------------------------------------------------------------------------


def test_content_tokens_strips_stopwords_and_non_content():
    assert "street" in content_tokens("people walking on a street")
    assert content_tokens("the a an of") == set()
    assert "person" in content_tokens("PERSON")


# ---------------------------------------------------------------------------
# Download script safety invariants
# ---------------------------------------------------------------------------


def test_manifest_is_curated_and_bounded():
    assert len(download.MANIFEST) == 14
    images = [i for i in download.MANIFEST if i["kind"] == "image"]
    videos = [i for i in download.MANIFEST if i["kind"] == "video"]
    assert len(images) == 10
    assert len(videos) == 4


def test_manifest_items_have_required_metadata_fields():
    required = {
        "id", "kind", "local_filename", "media_type", "source_url",
        "source_site", "source_page", "license", "min_bytes",
    }
    for item in download.MANIFEST:
        assert required.issubset(item.keys()), item["id"]
        assert item["source_url"].startswith("https://")


def test_download_script_accepts_no_url_argument():
    # The script must never download from user-supplied URLs (no crawling):
    # the CLI has no URL argument and no interactive/input() reading.
    import ast

    with open(download.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                assert not arg.value.startswith(("-", "--")) or "url" not in arg.value.lower(), arg.value
    assert not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "input"
        for n in ast.walk(tree)
    )


def test_download_script_never_executes_downloads():
    import ast

    with open(download.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    # Forbidden constructs: subprocess/Popen/os.system (executing the payload),
    # eval/exec (dynamic code), os.startfile.
    dangerous = {"subprocess", "os.system", "eval", "exec", "os.startfile", "Popen", "popen"}
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            used.add(node.func.attr)
            if isinstance(node.func.value, ast.Name):
                used.add(node.func.value.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            used.add(node.func.id)
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                used.add(a.name)
    assert not (dangerous & used), f"forbidden constructs found: {dangerous & used}"
    # Downloaded bytes are only ever written to a file opened for writing.
    # Ensure the payload is never opened for execution/import from the file.
    assert not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "exec"
        for n in ast.walk(tree)
    )


def test_download_script_only_targets_vlm_test_directory():
    import ast

    with open(download.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    assert "vlm_test" in download.DATA_DIR
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        v = node.value
        # Flag literals that look like filesystem paths outside vlm_test
        # ("data/x", drive letters, leading-slash paths). Bare directory
        # component "data" is fine (os.path.join(BASE_DIR, "data", "vlm_test")).
        looks_like_path = v.startswith(("D:", "C:")) or (
            v.startswith(("data", "/", "\\")) and ("/" in v or "\\" in v)
        )
        if looks_like_path and len(v) > 1 and not v.startswith(("http", "https")):
            assert "vlm_test" in v, f"suspicious path literal: {v}"


def test_validation_cases_reference_only_manifest_fixtures():
    manifest_ids = {item["id"] for item in download.MANIFEST}
    for case in validate.TEST_CASES:
        assert case.fixture_id in manifest_ids, case.case_id
        assert case.kind in ("image", "video")


def test_validation_cases_expect_unknown_exist():
    unknown = [c for c in validate.TEST_CASES if c.expect_unknown]
    assert len(unknown) >= 2
    for c in unknown:
        assert c.prohibited_themes  # must guard identity/intent-style claims


# ---------------------------------------------------------------------------
# Fixture / metadata consistency (optional - skipped when fixtures absent)
# ---------------------------------------------------------------------------


def _fixtures_present():
    if not os.path.exists(METADATA_FILE):
        return False
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        meta = json.load(f)
    records = {it["id"]: it for it in meta.get("items", [])}
    return all(
        os.path.exists(os.path.join(DATA_DIR, "images" if item["kind"] == "image" else "videos", item["local_filename"]))
        for item in download.MANIFEST if item["id"] in records
    ) and len(records) == len(download.MANIFEST)


pytestmark_has_fixtures = pytest.mark.skipif(
    not _fixtures_present(), reason="vlm_test fixtures not downloaded (offline/fresh clone)"
)


@pytest.mark.skipif(not _fixtures_present(), reason="vlm_test fixtures not downloaded")
def test_metadata_json_matches_manifest_and_is_verified():
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["dataset"]["classification"] == "INTERNET_TEST_DATA"
    records = {it["id"]: it for it in meta["items"]}
    assert set(records) == {i["id"] for i in download.MANIFEST}
    for item in download.MANIFEST:
        rec = records[item["id"]]
        assert rec["status"] == "ok"
        assert rec["sha256"] and len(rec["sha256"]) == 64
        assert rec["media_type"] == item["media_type"]
        assert rec["source_url"] == item["source_url"]
        assert "retrieval_date" in rec
        if item["kind"] == "image":
            assert rec["width"] and rec["height"]
        else:
            assert rec["duration_seconds"] and rec["duration_seconds"] > 0


@pytest.mark.skipif(not _fixtures_present(), reason="vlm_test fixtures not downloaded")
def test_fixture_hashes_match_disk(tmp_path):
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        meta = json.load(f)
    for rec in meta["items"]:
        sub = "images" if rec["kind"] == "image" else "videos"
        path = os.path.join(DATA_DIR, sub, rec["local_filename"])
        assert os.path.exists(path)
        assert download._sha256(path) == rec["sha256"]


@pytest.mark.skipif(not _fixtures_present(), reason="vlm_test fixtures not downloaded")
def test_validation_results_produced_offline():
    out = os.path.join(DATA_DIR, "validation_results.json")
    if not os.path.exists(out):
        pytest.skip("validation_results.json not generated yet")
    with open(out, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["classification"] == "INTERNET_TEST_DATA"
    assert data["dataset"] == "vlm_test"
    case_ids = {c["case_id"] for c in data["cases"]}
    assert case_ids == {c.case_id for c in validate.TEST_CASES}
    for c in data["cases"]:
        assert c["input"]["sha256"]
        assert c["input"]["source_url"]
        assert c["result"] in ("PASS", "FAIL", "SKIP", "ERROR")