"""Phase 6 integration tests: /investigation/search over forensic evidence.

Deterministic E2E (no mocks of the retrieval layer): real DB rows, real
embedding+in-memory-qdrant index seam, real FastAPI pipeline.

Covers: grounded answers (presence / track history), multi-camera isolation,
object-class filtering, negative/UNKNOWN queries (identity / intent / outside
view), RBAC (reviewer denied), bounded top_k, and 404s.
"""

import pytest

from app.core.config import settings
from app.investigation.query_parser import parse_query
from tests.investigation_testdata import (
    make_video_and_investigation,
    seed_evidence,
    user_id_by_email,
)

CAM = "P6-CAM"


# ----------------------------------------------------------------- fixtures


def _make_user(client, email, role="INVESTIGATOR"):
    client.post(
        "/auth/register",
        json={"email": email, "name": "P6", "password": "password123", "role": role},
    )
    res = client.post("/auth/login", json={"email": email, "password": "password123"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def _case(client, auth_headers, db):
    """A camera + bound video + investigation, plus seeded person/car evidence."""
    res = client.post(
        "/cameras",
        headers=auth_headers,
        json={"camera_name": CAM, "location": "P6 lot", "camera_type": "CCTV"},
    )
    assert res.status_code == 201, res.text
    cam_id = res.json()["id"]
    uid = user_id_by_email(db, "investigator@test.com")
    inv = make_video_and_investigation(db, cam_id, uid)
    session_id = inv.id
    seed_evidence(
        db, camera_id=cam_id, session_id=session_id, event_type="object_entered",
        tracking_id="T-100", label="person", timestamp=100.0, content_text="person entered the area tracking_id=T-100 label=person",
    )
    seed_evidence(
        db, camera_id=cam_id, session_id=session_id, event_type="object_stopped",
        tracking_id="T-100", label="person", timestamp=140.0, content_text="person stopped tracking_id=T-100 label=person",
    )
    seed_evidence(
        db, camera_id=cam_id, session_id=session_id, event_type="object_exited",
        tracking_id="T-100", label="person", timestamp=300.0, content_text="person left the area tracking_id=T-100 label=person",
    )
    seed_evidence(
        db, camera_id=cam_id, session_id=session_id, event_type="object_entered",
        tracking_id="T-200", label="car", timestamp=200.0, content_text="car entered the parking area tracking_id=T-200 label=car",
    )
    return cam_id, inv.id


@pytest.fixture
def _second_camera(client, auth_headers):
    res = client.post(
        "/cameras",
        headers=auth_headers,
        json={"camera_name": "P6-CAM-B", "location": "other site", "camera_type": "CCTV"},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


# --------------------------------------------------------------- query parser


def test_query_parser_presence_between():
    p = parse_query("Was there a person present between 10:00 and 10:15?")
    assert p.object_class == "person"
    assert p.question_type == "PRESENCE"
    assert p.temporal["start"] == 36000.0
    assert p.temporal["end"] == 36900.0


def test_query_parser_track_id():
    p = parse_query("Find all evidence for track TRK-0012")
    assert p.tracking_id == "TRK-0012"
    assert p.question_type == "TRACK_HISTORY"


def test_query_parser_unanswerable_intents():
    assert parse_query("Who is the person in the lot?").unanswerable
    assert parse_query("What was the person's intention?").unanswerable
    assert parse_query("What happened outside the camera view?").unanswerable


def test_query_parser_count_vehicles():
    p = parse_query("How many vehicles entered?")
    assert p.object_class == "car"
    assert p.question_type == "COUNT"


# ------------------------------------------------------------ API searches


def test_search_presence_answered(client, auth_headers, _case):
    cam_id, inv_id = _case
    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": "Was there a person present between 00:01 and 00:06?", "case_id": inv_id},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ANSWERED"
    assert body["answer"].startswith("YES")
    assert len(body["results"]) >= 1
    for r in body["results"]:
        assert r["camera_id"] == cam_id
    assert body["confidence"] > 0.0


def test_search_track_history(client, auth_headers, _case):
    cam_id, inv_id = _case
    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": "Find all evidence for track T-100", "case_id": inv_id},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ANSWERED"
    assert body["results"]
    assert all(r["tracking_id"] == "T-100" for r in body["results"])


def test_search_object_class_filter(client, auth_headers, _case):
    cam_id, inv_id = _case
    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": "Which cars entered the parking area?", "case_id": inv_id},
    )
    body = res.json()
    assert body["status"] == "ANSWERED"
    assert body["results"]
    assert all(r["object_class"] == "car" for r in body["results"])


def test_search_multi_camera_isolation(client, auth_headers, _case, _second_camera, db):
    cam_id, inv_id = _case
    # Evidence on a second camera must never leak into the case search.
    seed_evidence(
        db, camera_id=_second_camera, session_id=9999, event_type="object_entered",
        tracking_id="T-999", label="person", timestamp=120.0,
        content_text="person entered the other site tracking_id=T-999 label=person",
    )
    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": "Was there a person present between 00:01 and 00:06?", "case_id": inv_id},
    )
    body = res.json()
    assert body["status"] == "ANSWERED"
    assert body["results"]
    assert all(r["camera_id"] == cam_id for r in body["results"])
    assert all(r["tracking_id"] != "T-999" for r in body["results"])
    assert body["sources"]["camera_ids"] == [cam_id]


def test_search_identity_unknown(client, auth_headers, _case):
    cam_id, inv_id = _case
    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": "Who is the person in the parking lot?", "case_id": inv_id},
    )
    body = res.json()
    assert body["status"] == "UNKNOWN"
    assert "identity" in body["answer"].lower()
    assert body["results"] == []


def test_search_intent_unknown(client, auth_headers, _case):
    cam_id, inv_id = _case
    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": "What was the person's intention when they entered?", "case_id": inv_id},
    )
    body = res.json()
    assert body["status"] == "UNKNOWN"
    assert "intent" in body["answer"].lower()


def test_search_outside_view_unknown(client, auth_headers, _case):
    cam_id, inv_id = _case
    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": "What happened outside the camera view?", "case_id": inv_id},
    )
    body = res.json()
    assert body["status"] == "UNKNOWN"
    assert body["results"] == []


def test_search_no_match_insufficient(client, auth_headers, _case):
    cam_id, inv_id = _case
    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": "Was there a bicycle present between 00:01 and 00:06?", "case_id": inv_id},
    )
    body = res.json()
    assert body["status"] == "UNKNOWN"
    assert "INSUFFICIENT EVIDENCE" in body["answer"].upper()


def test_search_reviewer_forbidden(client, reviewer_headers, _case):
    cam_id, inv_id = _case
    res = client.post(
        "/investigation/search",
        headers=reviewer_headers,
        json={"query": "Was there a person present?", "case_id": inv_id},
    )
    assert res.status_code in (401, 403)


def test_search_unauthenticated_forbidden(client, _case):
    cam_id, inv_id = _case
    res = client.post(
        "/investigation/search", json={"query": "any person?", "case_id": inv_id}
    )
    assert res.status_code in (401, 403)


def test_search_top_k_bounded(client, auth_headers, _case, db):
    cam_id, inv_id = _case
    # Seed 20 more person events -> context must stay within configured caps.
    for i in range(20):
        seed_evidence(
            db, camera_id=cam_id, session_id=inv_id, event_type="object_entered",
            tracking_id=f"T-M{i}", label="person", timestamp=float(150 + i),
            content_text=f"person entered tracking_id=T-M{i} label=person",
        )
    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": "Was there a person present between 00:01 and 00:06?", "case_id": inv_id},
    )
    body = res.json()
    assert body["status"] == "ANSWERED"
    assert len(body["results"]) <= settings.RAG_MAX_CONTEXT_ITEMS


def test_search_unknown_case_404(client, auth_headers, _case):
    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": "any person?", "case_id": 999999},
    )
    assert res.status_code == 404


def test_search_empty_query_422(client, auth_headers, _case):
    cam_id, inv_id = _case
    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": "", "case_id": inv_id},
    )
    assert res.status_code == 422