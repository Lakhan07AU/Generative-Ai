"""Phase 8 - forensic verification, timeline reconstruction & reporting tests.

The stack is deterministic and independence-driven: evidence is seeded through
the same seams Phase 6/7 use (SQLite + in-memory embeddings/Qdrant), runs are
built against that evidence, and the forensic pipeline is exercised both
directly and through the API (analyze -> finding review -> report lifecycle),
including RBAC and the safety rails (no invented timeline events, no causality
or identity claims, VLM-only text never upgraded to OBSERVED).
"""

from __future__ import annotations

import json

import pytest

from app.database import models
from app.evidence.schemas import serialize_metadata
from app.forensic import multicamera, pipeline, store as forensics_store
from tests.investigation_testdata import make_video_and_investigation, seed_evidence, user_id_by_email

CAM = "P8-CAM-A"


@pytest.fixture
def _case(client, auth_headers, db):
    res = client.post(
        "/cameras",
        headers=auth_headers,
        json={"camera_name": CAM, "location": "P8 site", "camera_type": "CCTV"},
    )
    assert res.status_code == 201, res.text
    cam_id = res.json()["id"]
    uid = user_id_by_email(db, "investigator@test.com")
    inv = make_video_and_investigation(db, cam_id, uid)
    return cam_id, inv.id


def _seed(db, camera_id, session_id, **kw):
    return seed_evidence(db, camera_id=camera_id, session_id=session_id, **kw)


def _seed_vlm(db, camera_id, session_id, *, observation_id, items_text, timestamp=36124.0):
    public_id = f"EVD-VLM-{observation_id}"
    items = [{"text": text, "type": "observation", "category": "object"} for text in items_text]
    row = models.ForensicEvidence(
        public_id=public_id,
        evidence_type="VLM_OBSERVATION",
        source="DERIVED",
        camera_id=camera_id,
        session_id=session_id,
        vlm_observation_id=observation_id,
        window_start=timestamp,
        window_end=timestamp,
        frame_timestamp=timestamp,
        storage_path="demo/vlm.json",
        mime_type="application/json",
        sha256="b" * 64,
        content_text="vlm observation",
        extra_metadata=serialize_metadata({"items": items, "summary": "A vehicle is present in the lot."}),
        provenance="{}",
        index_status="INDEXED",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _make_run(db, inv_id, query, result):
    run = models.InvestigationRun(
        investigation_id=inv_id,
        status="COMPLETED",
        query=query,
        result=json.dumps(result),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _result_for(ids, conflicts=None):
    return {
        "query": "What happened at the scene?",
        "status": "COMPLETED",
        "findings": [],
        "conflicts": conflicts or [],
        "timeline": [],
        "evidence_used": [{"evidence_id": pid} for pid in ids],
        "limitations": [],
    }


def _analyze(db, inv, cam_id, run):
    return pipeline.analyze_run(db, run, inv, user_id=None, camera_ids=[cam_id])


# ---------------------------------------------------------------------------
# Timestamp normalisation
# ---------------------------------------------------------------------------


def test_timestamp_normalization_never_uses_vlm_processing_time(db, _case):
    cam_id, inv_id = _case
    event = _seed(db, cam_id, inv_id, event_type="object_entered", tracking_id="T-A", label="person", timestamp=36120.0)
    from app.forensic import timestamps as tsmod

    assert tsmod.event_time_of(event) == 36120.0
    assert tsmod.format_hhmmss(36120.0) == "10:02:00"
    assert tsmod.format_hhmmss(25200) == "07:00:00"
    assert tsmod.normalize_timestamp("123.5") == 123.5
    assert tsmod.normalize_timestamp("not-a-time") is None
    assert tsmod.normalize_timestamp(None) is None


def test_timeline_uses_frame_timestamp_not_analysis_time(db, _case):
    cam_id, inv_id = _case
    vlm = _seed_vlm(
        db, cam_id, inv_id,
        observation_id="OBS-1", items_text=["[OBSERVED] a car is visible"], timestamp=36130.0,
    )
    from app.forensic import timestamps as tsmod

    assert tsmod.event_time_of(vlm) == 36130.0


# ---------------------------------------------------------------------------
# Timeline reconstruction (ordering, merging, no invention)
# ---------------------------------------------------------------------------


def test_timeline_is_chronological_and_never_invents(db, _case):
    cam_id, inv_id = _case
    e1 = _seed(db, cam_id, inv_id, event_type="object_entered", tracking_id="T-A", label="person", timestamp=100.0)
    e2 = _seed(db, cam_id, inv_id, event_type="object_stopped", tracking_id="T-A", label="person", timestamp=140.0)
    e3 = _seed(db, cam_id, inv_id, event_type="object_entered", tracking_id="T-B", label="car", timestamp=200.0)
    e4 = _seed(db, cam_id, inv_id, event_type="object_exited", tracking_id="T-A", label="person", timestamp=300.0)
    run = _make_run(db, inv_id, "What happened at the scene?", _result_for([e1.public_id, e2.public_id, e3.public_id, e4.public_id]))
    inv = db.query(models.Investigation).get(inv_id)
    analysis = _analyze(db, inv, cam_id, run)

    timeline = analysis["timeline"]
    times = [t["timestamp"] for t in timeline]
    assert times == sorted(times)
    assert len(timeline) == 4
    for entry in timeline:
        assert entry["timeline_event_id"].startswith("TL-")
        assert "event_time" in entry
        assert "analysis_time" in entry
        assert "storage_time" in entry
        desc = entry["description"]
        assert any(
            desc.startswith(p)
            for p in ("The tracking system recorded", "The available evidence", "A source frame", "VLM observation")
        )


def test_timeline_merges_same_track_same_event_within_epsilon(db, _case):
    cam_id, inv_id = _case
    e1 = _seed(db, cam_id, inv_id, event_type="object_stopped", tracking_id="T-A", label="person", timestamp=140.0)
    e2 = _seed(db, cam_id, inv_id, event_type="object_stopped", tracking_id="T-A", label="person", timestamp=140.9)
    run = _make_run(db, inv_id, "Q", _result_for([e1.public_id, e2.public_id]))
    inv = db.query(models.Investigation).get(inv_id)
    analysis = _analyze(db, inv, cam_id, run)
    stopped = [t for t in analysis["timeline"] if t.get("event_type") == "object_stopped"]
    assert len(stopped) == 1
    assert set(stopped[0]["evidence_ids"]) == {e1.public_id, e2.public_id}
    assert stopped[0]["end_timestamp"] == 140.9


def test_distinct_times_produce_distinct_entries(db, _case):
    cam_id, inv_id = _case
    e1 = _seed(db, cam_id, inv_id, event_type="object_entered", tracking_id="T-A", label="person", timestamp=100.0)
    e2 = _seed(db, cam_id, inv_id, event_type="object_exited", tracking_id="T-A", label="person", timestamp=300.0)
    run = _make_run(db, inv_id, "Q", _result_for([e1.public_id, e2.public_id]))
    inv = db.query(models.Investigation).get(inv_id)
    analysis = _analyze(db, inv, cam_id, run)
    assert len(analysis["timeline"]) == 2


def test_conflicting_evidence_is_flagged_not_resolved(db, _case):
    cam_id, inv_id = _case
    e1 = _seed(db, cam_id, inv_id, event_type="object_entered", tracking_id="T-C", label="person", timestamp=36120.0)
    e2 = _seed(db, cam_id, inv_id, event_type="object_exited", tracking_id="T-C", label="person", timestamp=36122.0)
    conflicts = [
        {
            "evidence_a": e1.public_id,
            "evidence_b": e2.public_id,
            "type": "conflicting_event_timestamps",
            "reason": "Same track has two different events at nearly the same time",
        }
    ]
    run = _make_run(db, inv_id, "Q", _result_for([e1.public_id, e2.public_id], conflicts=conflicts))
    inv = db.query(models.Investigation).get(inv_id)
    analysis = _analyze(db, inv, cam_id, run)

    conflicting_entries = [t for t in analysis["timeline"] if t["classification"] == "CONFLICTING"]
    assert len(conflicting_entries) == 2
    assert all(t["verification_status"] == "CONTRADICTED" for t in conflicting_entries)
    assert analysis["contradictions"], "contradictions must be surfaced"
    assert any(c["evidence_a"] == e1.public_id and c["evidence_b"] == e2.public_id for c in analysis["contradictions"])


def test_vlm_observed_merges_with_its_source_frames(db, _case):
    cam_id, inv_id = _case
    vlm = _seed_vlm(db, cam_id, inv_id, observation_id="OBS-2", items_text=["[OBSERVED] a car is visible"], timestamp=36124.0)
    frame = _seed(
        db, cam_id, inv_id, evidence_type="FRAME", source="RAW_SOURCE",
        event_type=None, tracking_id=None, timestamp=36124.0,
        vlm_observation_id="OBS-2", content_text="frame capture vlm_observation_id=OBS-2",
    )
    run = _make_run(db, inv_id, "Q", _result_for([vlm.public_id, frame.public_id]))
    inv = db.query(models.Investigation).get(inv_id)
    analysis = _analyze(db, inv, cam_id, run)
    assert len(analysis["timeline"]) == 1
    entry = analysis["timeline"][0]
    assert entry["classification"] == "OBSERVED"
    assert "a car is visible" in entry["description"]


# ---------------------------------------------------------------------------
# Finding verification + support scoring
# ---------------------------------------------------------------------------


def test_verification_scores_observed_track_finding_high(db, _case):
    cam_id, inv_id = _case
    e1 = _seed(db, cam_id, inv_id, event_type="object_entered", tracking_id="T-A", label="person", timestamp=100.0)
    run = _make_run(db, inv_id, "Q", _result_for([e1.public_id]))
    inv = db.query(models.Investigation).get(inv_id)
    analysis = _analyze(db, inv, cam_id, run)

    finding = analysis["findings"][0]
    assert finding["classification"] == "OBSERVED"
    assert finding["verification_status"] == "VERIFIED"
    assert finding["evidence_support"] >= 0.8
    labels = [f["label"] for f in finding["support_factors"]]
    assert any("direct visual" in label for label in labels)
    assert any("track match" in label for label in labels)
    assert any("timestamp match" in label for label in labels)
    assert finding["causality_safe"] is True
    assert "support" in finding["support_reason"].lower()


def test_frame_only_low_resolution_never_becomes_observed(db, _case):
    cam_id, inv_id = _case
    frame = _seed(
        db, cam_id, inv_id, evidence_type="FRAME", source="RAW_SOURCE",
        event_type=None, tracking_id=None, timestamp=500.0,
        content_text="source frame 320x240 fps=1",
    )
    run = _make_run(db, inv_id, "Q", _result_for([frame.public_id]))
    inv = db.query(models.Investigation).get(inv_id)
    analysis = _analyze(db, inv, cam_id, run)
    entry = analysis["timeline"][0]
    assert entry["classification"] != "OBSERVED"
    assert "LOW_RESOLUTION" in entry["quality_flags"]
    finding = analysis["findings"][0]
    assert finding["classification"] != "OBSERVED"


# ---------------------------------------------------------------------------
# Sequencing / multi-camera / gaps
# ---------------------------------------------------------------------------


def test_sequencing_is_never_causal(db, _case):
    cam_id, inv_id = _case
    e1 = _seed(db, cam_id, inv_id, event_type="object_entered", tracking_id="T-A", label="person", timestamp=100.0)
    e2 = _seed(db, cam_id, inv_id, event_type="object_exited", tracking_id="T-A", label="person", timestamp=300.0)
    run = _make_run(db, inv_id, "Q", _result_for([e1.public_id, e2.public_id]))
    inv = db.query(models.Investigation).get(inv_id)
    analysis = _analyze(db, inv, cam_id, run)
    rels = analysis["relationships"]
    assert rels
    for rel in rels:
        assert rel["causal"] is False
        assert "causation" in rel["causality_note"].lower()


def test_multicamera_correlation_is_possible_not_definite():
    entries = [
        {"timeline_event_id": "TL-01", "track_id": "T-MC", "camera_id": 1, "camera_name": "Cam-A", "timestamp": 100.0, "end_timestamp": None},
        {"timeline_event_id": "TL-02", "track_id": "T-MC", "camera_id": 2, "camera_name": "Cam-B", "timestamp": 160.0, "end_timestamp": None},
    ]
    results = multicamera.correlate_across_cameras(entries)
    assert len(results) == 1
    assert results[0]["status"] == "POSSIBLE_CORRELATION"
    assert "required before treating these as the same object" in results[0]["note"]
    assert results[0]["status"] != "SAME_OBJECT"


def test_gaps_report_missing_ranges_and_coverage(db, _case):
    cam_id, inv_id = _case
    e1 = _seed(db, cam_id, inv_id, event_type="object_entered", tracking_id="T-A", label="person", timestamp=100.0)
    e2 = _seed(db, cam_id, inv_id, event_type="object_exited", tracking_id="T-A", label="person", timestamp=250.0)
    run = _make_run(db, inv_id, "Q", _result_for([e1.public_id, e2.public_id]))
    inv = db.query(models.Investigation).get(inv_id)
    analysis = _analyze(db, inv, cam_id, run)
    gaps = analysis["gaps"]["gaps"]
    kinds = {g["kind"] for g in gaps}
    assert "missing_time_ranges" in kinds
    assert "missing_camera_coverage" in kinds
    time_gap = [g for g in gaps if g["kind"] == "missing_time_ranges"][0]
    assert time_gap["detail"][0]["start"] == 100.0
    assert time_gap["detail"][0]["end"] == 250.0


def test_unanswerable_run_analysis_is_honest(db, _case):
    cam_id, inv_id = _case
    run = _make_run(db, inv_id, "Who was driving the vehicle?", _result_for([]))
    inv = db.query(models.Investigation).get(inv_id)
    analysis = _analyze(db, inv, cam_id, run)
    assert analysis["timeline"] == []
    assert analysis["findings"] == []
    assert "insufficient" in analysis["summary"].lower()
    assert analysis["gaps"]["gaps"]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_analysis_and_timeline_rows_persisted(db, _case):
    cam_id, inv_id = _case
    e1 = _seed(db, cam_id, inv_id, event_type="object_entered", tracking_id="T-A", label="person", timestamp=100.0)
    run = _make_run(db, inv_id, "Q", _result_for([e1.public_id]))
    inv = db.query(models.Investigation).get(inv_id)
    _analyze(db, inv, cam_id, run)

    rows = db.query(models.ForensicTimelineEvent).filter(models.ForensicTimelineEvent.run_id == run.id).all()
    assert len(rows) == 1
    loaded = forensics_store.load_analysis(db, run.id)
    assert loaded["timeline"]
    assert loaded["metrics"]["total_seconds"] >= 0
    timeline_rows = forensics_store.load_timeline_rows(db, run.id)
    assert timeline_rows[0]["timeline_event_id"] == "TL-01"


def test_reanalyzing_replaces_analysis_not_source_evidence(db, _case):
    cam_id, inv_id = _case
    e1 = _seed(db, cam_id, inv_id, event_type="object_entered", tracking_id="T-A", label="person", timestamp=100.0)
    run = _make_run(db, inv_id, "Q", _result_for([e1.public_id]))
    inv = db.query(models.Investigation).get(inv_id)
    _analyze(db, inv, cam_id, run)
    _analyze(db, inv, cam_id, run)
    rows = db.query(models.ForensicTimelineEvent).filter(models.ForensicTimelineEvent.run_id == run.id).all()
    assert len(rows) == 1
    analyses = db.query(models.ForensicAnalysis).filter(models.ForensicAnalysis.run_id == run.id).all()
    assert len(analyses) == 1


# ---------------------------------------------------------------------------
# API integration: analyze -> review -> report lifecycle + RBAC
# ---------------------------------------------------------------------------


def _start(client, headers, inv_id, query, **kw):
    payload = {"query": query}
    payload.update(kw)
    res = client.post(f"/investigations/{inv_id}/investigate", headers=headers, json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def _seed_scene(db, cam_id, inv_id, index=True):
    e1 = _seed(db, cam_id, inv_id, event_type="object_entered", tracking_id="T-A", label="person", timestamp=36120.0, index=index)
    e2 = _seed(db, cam_id, inv_id, event_type="object_stopped", tracking_id="T-A", label="person", timestamp=36124.0, index=index)
    e3 = _seed(db, cam_id, inv_id, event_type="object_exited", tracking_id="T-A", label="person", timestamp=36180.0, index=index)
    e4 = _seed(db, cam_id, inv_id, event_type="object_entered", tracking_id="T-B", label="car", timestamp=36140.0, index=index)
    return [e1, e2, e3, e4]


def test_api_forensic_analyze_end_to_end(client, auth_headers, db, _case):
    cam_id, inv_id = _case
    _seed_scene(db, cam_id, inv_id)
    body = _start(client, auth_headers, inv_id, "Find all evidence for track T-A", require_review=False)
    run_id = body["id"]
    assert body["status"] == "COMPLETED", body.get("error")

    res = client.post(f"/runs/{run_id}/forensic/analyze", headers=auth_headers)
    assert res.status_code == 200, res.text
    analysis = res.json()
    assert analysis["timeline"]
    assert analysis["findings"]
    for finding in analysis["findings"]:
        assert finding["evidence_support"] >= 0
        assert "support_factors" in finding
    assert "missing_camera_coverage" in {g["kind"] for g in analysis["gaps"]["gaps"]}
    assert analysis["metrics"]["timeline_seconds"] >= 0

    fetched = client.get(f"/runs/{run_id}/forensic", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["timeline_rows"]


def test_api_finding_review_flow_with_reviewer(client, auth_headers, reviewer_headers, db, _case):
    cam_id, inv_id = _case
    _seed_scene(db, cam_id, inv_id)
    body = _start(client, auth_headers, inv_id, "Find all evidence for track T-A", require_review=False)
    run_id = body["id"]
    analysis = client.post(f"/runs/{run_id}/forensic/analyze", headers=auth_headers).json()
    finding_id = analysis["findings"][0]["finding_id"]

    res = client.post(
        f"/runs/{run_id}/findings/{finding_id}/review",
        headers=reviewer_headers,
        json={"action": "ACCEPTED", "comment": "matches the frames"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["finding_id"] == finding_id
    assert res.json()["action"] == "ACCEPTED"

    reviews = client.get(f"/runs/{run_id}/reviews", headers=auth_headers).json()
    assert any(r["finding_id"] == finding_id for r in reviews["finding_reviews"])

    audit = db.query(models.AuditLog).filter(models.AuditLog.action == "finding_review").count()
    assert audit >= 1


def test_api_reviewer_cannot_analyze(client, reviewer_headers, auth_headers, db, _case):
    cam_id, inv_id = _case
    _seed_scene(db, cam_id, inv_id)
    _start(client, auth_headers, inv_id, "Find all evidence for track T-A", require_review=False)
    live_body = _start(client, auth_headers, inv_id, "Find all evidence for track T-A", require_review=False)
    run_id = live_body["id"]
    forbidden = client.post(f"/runs/{run_id}/forensic/analyze", headers=reviewer_headers)
    assert forbidden.status_code == 403


def _auth_headers(client):
    client.post(
        "/auth/register",
        json={"email": "p8admin@test.com", "name": "P8 Admin", "password": "password123", "role": "ADMIN"},
    )
    res = client.post("/auth/login", json={"email": "p8admin@test.com", "password": "password123"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_api_report_requires_completed_run(client, reviewer_headers, db, _case):
    cam_id, inv_id = _case
    _seed_scene(db, cam_id, inv_id)
    admin = _auth_headers(client)
    body = _start(client, admin, inv_id, "Find all evidence for track T-A", require_review=True)
    run_id = body["id"]
    assert body["status"] == "READY_FOR_REVIEW", body.get("error")

    analyzed = client.post(f"/runs/{run_id}/forensic/analyze", headers=admin)
    assert analyzed.status_code == 200

    before = client.post(f"/runs/{run_id}/report", headers=admin)
    assert before.status_code == 409, before.text

    res = client.post(f"/runs/{run_id}/review", headers=reviewer_headers, json={"decision": "APPROVE", "note": "ok"})
    assert res.status_code == 200, res.text

    report = client.post(f"/runs/{run_id}/report", headers=admin)
    assert report.status_code == 200, report.text
    meta = report.json()
    assert meta["file_format"] in ("pdf", "markdown")
    assert meta["storage_path"]

    detail = client.get(f"/runs/{run_id}/report", headers=admin)
    assert detail.status_code == 200
    content = detail.json()["content"]
    expected_keys = {
        "case_information", "investigation_question", "executive_summary", "timeline",
        "verified_findings", "unverified_findings", "conflicting_evidence", "evidence_gaps",
        "supporting_evidence", "vlm_observations", "track_information", "camera_information",
        "limitations", "reviewer_information", "audit_information",
    }
    assert expected_keys.issubset(content.keys())

    file_res = client.get(f"/runs/{run_id}/report/file", headers=admin)
    assert file_res.status_code == 200
    assert file_res.content
    assert file_res.headers["content-type"].startswith(("application/pdf", "text/markdown"))

    again = client.post(f"/runs/{run_id}/report", headers=admin)
    assert again.status_code == 200
    assert int(again.json()["version"]) > int(meta["version"])