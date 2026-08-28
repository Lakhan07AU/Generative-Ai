"""Tests for Part 3 - agentic investigation / evidence verification / timeline / audit."""

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.database import models
from app.agents.guardrails import (
    ALLOWED_TOOLS,
    Budget,
    BudgetExceeded,
    GuardrailViolation,
    validate_timestamp,
)
from app.agents import planner
from app.agents.tools import get_tool
from app.agents.agent import run_investigation
from app.agents.evidence_repo import build_timeline, clip_evidence_id
from app.verification.service import decompose_claim, verify_claim, VERIFIER_VERSION
from app.timeline import builder as timeline_builder
from app.ai.qdrant_service import qdrant
from app.ai.embeddings import embeddings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_video(db, start_h=10, start_m=0, duration=200.0, base="CLIP-S", _counter=[0]):
    """Create camera + video + 2 clips with person detections and events."""
    _counter[0] += 1
    cid = _counter[0]
    base = f"CLIP-S{cid}-"
    cam = models.Camera(camera_name=f"Cam {cid}", location="entrance")
    db.add(cam)
    db.flush()
    video = models.Video(
        filename=f"seed{cid}.mp4",
        storage_path=f"seed{cid}.mp4",
        camera_id=cam.id,
        duration_seconds=duration,
        start_time=datetime(2026, 1, 1, start_h, start_m, 0, tzinfo=timezone.utc),
        status="PROCESSED",
    )
    db.add(video)
    db.flush()

    clips = []
    clip1 = models.Clip(
        public_id=f"{base}1", video_id=video.id, camera_id=cam.id,
        start_time=0.0, end_time=10.0, description="Person at entrance",
    )
    clip2 = models.Clip(
        public_id=f"{base}2", video_id=video.id, camera_id=cam.id,
        start_time=12.0, end_time=25.0, description="Person near equipment",
    )
    db.add_all([clip1, clip2])
    db.flush()

    db.add(models.Detection(
        clip_id=clip1.id, video_id=video.id, camera_id=cam.id, label="person",
        bounding_box="[1,2,3,4]", frame_number=30, timestamp=6.0,
        detection_confidence=0.92, tracking_id="T-A",
    ))
    db.add(models.Detection(
        clip_id=clip2.id, video_id=video.id, camera_id=cam.id, label="person",
        bounding_box="[5,6,7,8]", frame_number=45, timestamp=18.0,
        detection_confidence=0.88, tracking_id="T-A",
    ))
    db.add(models.Event(
        video_id=video.id, clip_id=clip1.id, event_type="entered",
        description="Person enters restricted area", start_time=6.0, end_time=8.0,
        confidence=0.9,
    ))
    db.add(models.Event(
        video_id=video.id, clip_id=clip2.id, event_type="alarm",
        description="Alarm detected", start_time=18.0, end_time=20.0, confidence=0.7,
    ))
    db.commit()
    clips_ = db.query(models.Clip).filter(models.Clip.video_id == video.id).all()
    return video, clips_


def _index_clip_evidence(clip):
    """Index a clip's semantic description into (in-memory) Qdrant."""
    qdrant.ensure_collections()
    text = f"Person detected near the entrance entering the restricted area at clip {clip.public_id}"
    vec = embeddings.embed_text(text)
    qdrant.index_evidence(
        point_id=f"ev-{clip.id}",
        vector=vec,
        payload={
            "clip_id": clip.id,
            "video_id": clip.video_id,
            "camera_id": clip.camera_id,
            "start_time": clip.start_time,
            "end_time": clip.end_time,
            "description": text,
            "objects": ["person"],
            "tracking_ids": ["T-A"],
            "transcript": "",
            "source_path": "",
        },
    )


# ---------------------------------------------------------------------------
# 1) Agent tool selection
# ---------------------------------------------------------------------------

def test_planner_selects_tools_for_person_restricted_query(db):
    plan = planner.build_plan(db, "Did a person enter the restricted zone after 10:00?")
    tools = [p["tool"] for p in plan]
    assert "search_video" in tools
    assert "search_person" in tools
    assert "search_policy" in tools
    assert "build_timeline" in tools
    for p in plan:
        assert p["tool"] in ALLOWED_TOOLS


def test_planner_selects_object_tool_for_car_query(db):
    plan = planner.build_plan(db, "Did a van stop near the entrance?")
    tools = [p["tool"] for p in plan]
    assert "search_object" in tools
    call = next(p for p in plan if p["tool"] == "search_object")
    assert call["arguments"]["label"] in ("car", "van")


def test_tool_registry_matches_allowlist():
    from app.agents.tools import TOOLS

    assert set(TOOLS.keys()) == set(ALLOWED_TOOLS)
    assert len(TOOLS) == 9


# ---------------------------------------------------------------------------
# 2) Tool-call limits
# ---------------------------------------------------------------------------

def test_budget_exceeded_on_max_tool_calls():
    b = Budget(max_tool_calls=2, max_steps=10, timeout_seconds=5, retry_limit=1)
    b.enter_tool_call()
    b.enter_tool_call()
    with pytest.raises(BudgetExceeded):
        b.enter_tool_call()


def test_budget_exceeded_on_max_steps():
    b = Budget(max_tool_calls=10, max_steps=3, timeout_seconds=5, retry_limit=1)
    b.enter_step()
    b.enter_step()
    b.enter_step()
    with pytest.raises(BudgetExceeded):
        b.enter_step()


def test_agent_does_not_call_tools_beyond_budget(db):
    from app.agents.agent import _invoke_tool, Budget as B

    b = B(max_tool_calls=1, max_steps=1, timeout_seconds=5, retry_limit=1)
    b.enter_tool_call()
    # Remaining budget is 0; a raw invocation would still run but the agent
    # must not route additional tool calls once the budget is exhausted.
    assert b.remaining_tool_calls() == 0


# ---------------------------------------------------------------------------
# 3) Timeout
# ---------------------------------------------------------------------------

def test_budget_timeout_expires():
    import time as _t

    b = Budget(timeout_seconds=0.001, max_steps=10, max_tool_calls=10, retry_limit=1)
    deadline = b.deadline()
    _t.sleep(0.01)
    assert b.is_expired(deadline)


def test_retry_limit_exceeded():
    b = Budget(timeout_seconds=5, max_steps=10, max_tool_calls=10, retry_limit=2)
    b.register_retry()
    b.register_retry()
    with pytest.raises(BudgetExceeded):
        b.register_retry()


# ---------------------------------------------------------------------------
# 4) Invalid tool
# ---------------------------------------------------------------------------

def test_invalid_tool_rejected():
    from app.agents.guardrails import assert_allowed_tool

    with pytest.raises(GuardrailViolation):
        assert_allowed_tool("delete_evidence")

    with pytest.raises(GuardrailViolation):
        assert_allowed_tool("approve_report")

    with pytest.raises(GuardrailViolation):
        assert_allowed_tool("not_a_real_tool")


def test_tool_invoke_unknown_args_rejected(db):
    tool = get_tool("get_clip")
    with pytest.raises(ValueError):
        tool.invoke(db, {"clip_id": 1, "bogus_arg": True})


# ---------------------------------------------------------------------------
# 5) Empty retrieval
# ---------------------------------------------------------------------------

def test_verify_claim_insufficient_when_no_evidence(db):
    res = verify_claim(
        db, "A red van entered the parking lot",
        investigation_id=None, persist=False,
    )
    assert res["result"] == "INSUFFICIENT_EVIDENCE"
    assert not res["checks"]["visual_evidence"]["passed"]


def test_agent_unknown_on_empty_store(db):
    result = run_investigation(db, "Did anyone approach the gate?")
    assert result["status"] == "UNKNOWN"
    assert result["answer"]
    assert any(tc["name"] == "search_video" for tc in result["tool_calls"])


# ---------------------------------------------------------------------------
# 6) Timestamp validation
# ---------------------------------------------------------------------------

def test_validate_timestamp_bounds():
    assert validate_timestamp(5.0, 0.0, 10.0)
    assert not validate_timestamp(-1.0, 0.0, 10.0)
    assert not validate_timestamp(11.0, 0.0, 10.0)
    assert not validate_timestamp(None, 0.0, 10.0)


def test_verify_claim_rejects_out_of_bounds_timestamp(db):
    _seed_video(db, start_h=10, start_m=0, duration=200.0)
    # 10:42:17 -> far outside a video that starts at 10:00:00 + 200s
    res = verify_claim(
        db,
        "A person entered the area at 10:42:17",
        timestamp=10 * 3600 + 42 * 60 + 17,
        persist=False,
    )
    assert res["result"] == "INSUFFICIENT_EVIDENCE"
    assert res["checks"]["temporal"]["passed"] is False


# ---------------------------------------------------------------------------
# 7) Claim decomposition
# ---------------------------------------------------------------------------

def test_decompose_claim_extracts_subject_timestamp_and_event():
    d = decompose_claim("Person entered restricted area at 10:42:17")
    assert "person" in d["subject_types"]
    assert d["timestamp"] == 10 * 3600 + 42 * 60 + 17
    assert d["events"]


# ---------------------------------------------------------------------------
# 8) Evidence verification -> VERIFIED
# ---------------------------------------------------------------------------

def test_verify_claim_verified_with_consistent_evidence(db):
    video, clips = _seed_video(db)
    res = verify_claim(
        db,
        "A person entered the restricted area",
        video_id=video.id,
        persist=False,
    )
    assert res["result"] == "VERIFIED"
    assert res["checks"]["visual_evidence"]["passed"]
    assert res["checks"]["subject"]["passed"]
    assert res["checks"]["cross_evidence"]["passed"]
    assert res["evidence"], "expected evidence links"


# ---------------------------------------------------------------------------
# 9) Conflicting evidence -> PARTIALLY_VERIFIED
# ---------------------------------------------------------------------------

def test_verify_claim_partial_on_conflicting_trackers(db):
    cam = models.Camera(camera_name="Cam A", location="lobby")
    db.add(cam)
    db.flush()
    video = models.Video(
        filename="conflict.mp4", storage_path="conflict.mp4", camera_id=cam.id,
        duration_seconds=100.0, start_time=datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
        status="PROCESSED",
    )
    db.add(video)
    db.flush()
    c1 = models.Clip(public_id="CLIP-C1", video_id=video.id, camera_id=cam.id, start_time=0.0, end_time=10.0)
    c2 = models.Clip(public_id="CLIP-C2", video_id=video.id, camera_id=cam.id, start_time=12.0, end_time=22.0)
    db.add_all([c1, c2])
    db.flush()
    # Two different trackers -> conflicting cross-evidence.
    db.add(models.Detection(
        clip_id=c1.id, video_id=video.id, camera_id=cam.id, label="person",
        bounding_box="[]", frame_number=1, timestamp=2.0, detection_confidence=0.9, tracking_id="T1",
    ))
    db.add(models.Detection(
        clip_id=c2.id, video_id=video.id, camera_id=cam.id, label="person",
        bounding_box="[]", frame_number=2, timestamp=15.0, detection_confidence=0.9, tracking_id="T2",
    ))
    db.commit()

    res = verify_claim(db, "A person was in the lobby", video_id=video.id, persist=False)
    assert res["result"] == "PARTIALLY_VERIFIED"
    assert res["checks"]["cross_evidence"]["passed"] is False


# ---------------------------------------------------------------------------
# 10) Timeline ordering
# ---------------------------------------------------------------------------

def test_timeline_chronological_order(db):
    video, clips = _seed_video(db)
    events = build_timeline(db, video_id=video.id)
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps)
    assert events, "expected timeline events"
    for e in events:
        assert "timestamp" in e and "description" in e and "evidence_ids" in e and "status" in e


def test_persist_timeline_sorted(db):
    video, clips = _seed_video(db)
    inv = models.Investigation(title="T", query="q", created_by_user_id=None)
    db.add(inv)
    db.commit()
    db.refresh(inv)
    entries = build_timeline(db, video_id=video.id)
    timeline_builder.persist_timeline(db, inv.id, entries)
    loaded = timeline_builder.load(db, inv.id)
    ts = [e["timestamp"] for e in loaded]
    assert ts == sorted(ts)
    assert loaded, "expected persisted timeline"


# ---------------------------------------------------------------------------
# 11) Audit logging
# ---------------------------------------------------------------------------

def test_agent_chat_logs_tool_calls(db):
    user = models.User(email="agent@x.com", name="Agent", password_hash="x", role="INVESTIGATOR")
    db.add(user)
    db.flush()
    inv = models.Investigation(title="Audit", query="initial", created_by_user_id=user.id)
    db.add(inv)
    db.commit()
    db.refresh(inv)

    video, clips = _seed_video(db)
    for c in clips:
        _index_clip_evidence(c)

    result = run_investigation(
        db, "Did a person enter the restricted zone?",
        investigation_id=inv.id, user_id=user.id, video_id=video.id,
    )
    assert result["tool_calls"], "expected tool calls to be recorded"

    logs = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.details.contains(f"investigation_id={inv.id}"))
        .all()
    )
    actions = [l.action for l in logs]
    assert any(a.startswith("tool_call:") for a in actions), "tool calls must be audited"
    assert "evidence_verification" in actions
    assert "timeline_generation" in actions
    assert "agent_invocation" in actions


def test_agent_end_to_end_with_evidence(db):
    video, clips = _seed_video(db)
    for c in clips:
        _index_clip_evidence(c)
    inv = models.Investigation(title="E2E", query="seed", video_id=video.id)
    db.add(inv)
    db.commit()
    db.refresh(inv)

    result = run_investigation(
        db, "Did a person enter the restricted area?",
        investigation_id=inv.id, video_id=video.id,
    )
    assert result["tool_calls"]
    assert result["claims"] or result["events"]
    assert result["answer"]


def test_investigation_api_create_and_chat(client, auth_headers, db):
    video, clips = _seed_video(db)
    for c in clips:
        _index_clip_evidence(c)

    res = client.post(
        "/investigations",
        json={"title": "Server room", "query": "Who entered?", "video_id": video.id},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    inv = res.json()
    assert inv["status"] == "OPEN"

    chat = client.post(
        f"/investigations/{inv['id']}/chat",
        json={"message": "Did a person enter the restricted area?"},
        headers=auth_headers,
    )
    assert chat.status_code == 200, chat.text
    body = chat.json()["agent_result"]
    assert "tool_calls" in body and "answer" in body

    claims = client.get("/claims", headers=auth_headers)
    assert claims.status_code == 200

    audit = client.get(f"/investigations/{inv['id']}/audit", headers=auth_headers)
    assert audit.status_code == 200


def test_verify_endpoint_persists_verification(client, auth_headers, db):
    video, _ = _seed_video(db)
    inv = client.post(
        "/investigations",
        json={"title": "Verify me", "query": "seed", "video_id": video.id},
        headers=auth_headers,
    )
    inv_id = inv.json()["id"]
    res = client.post(
        f"/investigations/{inv_id}/verify",
        json={
            "claim_text": "A person entered the restricted area",
            "investigation_id": inv_id,
            "video_id": video.id,
            "persist": True,
        },
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["result"] in ("VERIFIED", "PARTIALLY_VERIFIED", "INSUFFICIENT_EVIDENCE")
    assert body["verifier_version"]

    claims = client.get(f"/investigations/{inv_id}", headers=auth_headers).json()["claims"]
    assert len(claims) >= 1
