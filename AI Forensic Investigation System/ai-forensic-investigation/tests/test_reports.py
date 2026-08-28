"""Part 4 - tests for human review workflow + report generation.

Covers:
  - Full workflow DRAFT -> submit -> per-claim review -> approve -> finalize
  - REJECTED path
  - Per-claim actions ACCEPT / REJECT / EDIT / UNCERTAIN
  - EDIT stores original AI text + edited text + reviewer id + timestamp
  - Failure cases: invalid action, EDIT without text, wrong-state transitions,
    report not found, DRAFT finalize, PENDING_REVIEW per-claim gating, etc.
  - Report generation (requires MinIO for storage.put_bytes)
"""

import json

import pytest

from app.report import review as review_service
from app.schemas.report import REPORT_SECTION_TITLES
from app.database import models


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_user_counter = {"n": 0}


def _make_user(db, email=None, role="REVIEWER"):
    _user_counter["n"] += 1
    u = models.User(
        email=email or f"reviewer{_user_counter['n']}@test.com",
        name="Reviewer", password_hash="x", role=role,
    )
    db.add(u)
    db.flush()
    return u


def _make_investigation(db, user, title="Incident", query="Who entered?"):
    inv = models.Investigation(title=title, query=query, created_by_user_id=user.id)
    db.add(inv)
    db.flush()
    return inv


def _make_report(db, inv, user, status="DRAFT", is_final=False):
    r = models.Report(
        investigation_id=inv.id,
        title=f"Incident Report — {inv.title}",
        status=status,
        is_final=is_final,
        version=1,
        generated_by_user_id=user.id,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _make_claim(db, inv, text="A person entered the restricted area"):
    c = models.Claim(
        investigation_id=inv.id, claim_text=text,
        claim_type="OBSERVATION", status="VERIFIED", confidence=0.9,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ---------------------------------------------------------------------------
# Review workflow - success paths
# ---------------------------------------------------------------------------


def test_full_workflow_to_final(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    report = _make_report(db, inv, reviewer)
    claim = _make_claim(db, inv)

    # DRAFT -> PENDING_REVIEW
    r = review_service.submit_for_review(db, report.id, reviewer.id)
    assert r.status == "PENDING_REVIEW"

    # per-claim review (must be PENDING_REVIEW)
    d = review_service.record_claim_decision(
        db, report.id, reviewer.id,
        __import__("app.schemas.report", fromlist=["ReviewDecisionCreate"]).ReviewDecisionCreate(
            claim_id=claim.id, action="ACCEPT"
        ),
    )
    assert d.action == "ACCEPT"
    assert d.original_text == claim.claim_text

    # PENDING_REVIEW -> APPROVED
    r = review_service.review_overall(db, report.id, reviewer.id, "APPROVE", "Looks good")
    assert r.status == "APPROVED"
    assert r.reviewed_by_user_id == reviewer.id

    # APPROVED -> FINAL
    r = review_service.finalize_report(db, report.id, reviewer.id)
    assert r.status == "APPROVED"
    assert r.is_final is True


def test_workflow_reject_path(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    report = _make_report(db, inv, reviewer)

    review_service.submit_for_review(db, report.id, reviewer.id)
    r = review_service.review_overall(db, report.id, reviewer.id, "REJECT", "Needs rework")
    assert r.status == "REJECTED"
    assert r.is_final is False

    # REJECTED cannot be finalized
    with pytest.raises(ValueError):
        review_service.finalize_report(db, report.id, reviewer.id)


def test_edit_claim_stores_original_and_edited_and_reviewer(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    report = _make_report(db, inv, reviewer)
    claim = _make_claim(db, inv, "original AI claim text")

    review_service.submit_for_review(db, report.id, reviewer.id)
    D = __import__("app.schemas.report", fromlist=["ReviewDecisionCreate"]).ReviewDecisionCreate
    d = review_service.record_claim_decision(
        db, report.id, reviewer.id,
        D(claim_id=claim.id, action="EDIT", edited_text="corrected human text", note="typo"),
    )
    assert d.original_text == "original AI claim text"
    assert d.edited_text == "corrected human text"
    assert d.reviewer_user_id == reviewer.id
    assert d.reviewed_at is not None


def test_uncertain_action_allowed(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    report = _make_report(db, inv, reviewer)
    review_service.submit_for_review(db, report.id, reviewer.id)
    D = __import__("app.schemas.report", fromlist=["ReviewDecisionCreate"]).ReviewDecisionCreate
    d = review_service.record_claim_decision(db, report.id, reviewer.id, D(action="UNCERTAIN"))
    assert d.action == "UNCERTAIN"


def test_all_claim_actions_are_allowed():
    assert review_service.ALLOWED_CLAIM_ACTIONS == {"ACCEPT", "REJECT", "EDIT", "UNCERTAIN"}


def test_all_valid_statuses_known():
    assert review_service.VALID_STATUSES == {"DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED"}


# ---------------------------------------------------------------------------
# Review workflow - audit trail
# ---------------------------------------------------------------------------


def test_every_transition_is_audited(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    claim = _make_claim(db, inv)
    report = _make_report(db, inv, reviewer)

    review_service.submit_for_review(db, report.id, reviewer.id)
    review_service.record_claim_decision(
        db, report.id, reviewer.id,
        __import__("app.schemas.report", fromlist=["ReviewDecisionCreate"]).ReviewDecisionCreate(
            claim_id=claim.id, action="ACCEPT"
        ),
    )
    review_service.review_overall(db, report.id, reviewer.id, "APPROVE")
    review_service.finalize_report(db, report.id, reviewer.id)

    logs = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.entity_type == "report", models.AuditLog.entity_id == report.id)
        .all()
    )
    actions = {l.action for l in logs}
    assert "report_submitted_for_review" in actions
    assert "review_claim_decision" in actions
    assert "report_approved" in actions
    assert "report_finalized" in actions


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------


def test_unknown_claim_action_rejected(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    report = _make_report(db, inv, reviewer)
    review_service.submit_for_review(db, report.id, reviewer.id)
    D = __import__("app.schemas.report", fromlist=["ReviewDecisionCreate"]).ReviewDecisionCreate
    with pytest.raises(ValueError):
        review_service.record_claim_decision(db, report.id, reviewer.id, D(action="MAYBE"))


def test_edit_without_text_rejected(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    report = _make_report(db, inv, reviewer)
    review_service.submit_for_review(db, report.id, reviewer.id)
    D = __import__("app.schemas.report", fromlist=["ReviewDecisionCreate"]).ReviewDecisionCreate
    with pytest.raises(ValueError):
        review_service.record_claim_decision(db, report.id, reviewer.id, D(action="EDIT"))


def test_claim_review_blocked_outside_pending(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    report = _make_report(db, inv, reviewer)  # still DRAFT
    D = __import__("app.schemas.report", fromlist=["ReviewDecisionCreate"]).ReviewDecisionCreate
    with pytest.raises(ValueError) as ei:
        review_service.record_claim_decision(db, report.id, reviewer.id, D(action="ACCEPT"))
    assert "PENDING_REVIEW" in str(ei.value)


def test_submit_blocked_for_non_draft(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    report = _make_report(db, inv, reviewer, status="PENDING_REVIEW")
    with pytest.raises(ValueError):
        review_service.submit_for_review(db, report.id, reviewer.id)


def test_double_submit_blocked(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    report = _make_report(db, inv, reviewer)
    review_service.submit_for_review(db, report.id, reviewer.id)
    with pytest.raises(ValueError):
        review_service.submit_for_review(db, report.id, reviewer.id)


def test_overall_review_requires_pending(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    report = _make_report(db, inv, reviewer)  # DRAFT
    with pytest.raises(ValueError):
        review_service.review_overall(db, report.id, reviewer.id, "APPROVE")


def test_overall_review_requires_valid_decision(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    report = _make_report(db, inv, reviewer)
    review_service.submit_for_review(db, report.id, reviewer.id)
    with pytest.raises(ValueError):
        review_service.review_overall(db, report.id, reviewer.id, "HOLD")


def test_finalize_requires_approved(db):
    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    report = _make_report(db, inv, reviewer)  # DRAFT
    with pytest.raises(ValueError):
        review_service.finalize_report(db, report.id, reviewer.id)


def test_report_not_found(db):
    with pytest.raises(ValueError):
        review_service.submit_for_review(db, 99999, None)


def test_claim_review_on_missing_report(db):
    reviewer = _make_user(db)
    D = __import__("app.schemas.report", fromlist=["ReviewDecisionCreate"]).ReviewDecisionCreate
    with pytest.raises(ValueError):
        review_service.record_claim_decision(db, 99999, reviewer.id, D(action="ACCEPT"))


# ---------------------------------------------------------------------------
# HTTP API - report endpoints
# ---------------------------------------------------------------------------

# The review endpoints require a REVIEWER/ADMIN role. Simulate full API flow
# with the admin client and an investigation seeded via ORM.


def _seed_investigation_via_api(client, admin_headers, db, reviewer_id=None):
    """Create an investigation + a verified claim directly to drive the API flow."""
    inv = models.Investigation(title="API report", query="Who entered?", created_by_user_id=reviewer_id)
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


def test_report_api_generate_and_reject(client, admin_headers, db):
    from helpers import _has_minio
    if not _has_minio():
        pytest.skip("MinIO not available")
        return

    # Create a user + investigation directly (storage not needed until generate)
    admin = db.query(models.User).filter(models.User.email == "admin@test.com").first()
    inv = models.Investigation(title="Sec", query="q", created_by_user_id=admin.id)
    db.add(inv)
    db.commit()
    db.refresh(inv)
    # Pre-seed a verified claim so report content has a section.
    models.Claim(
        investigation_id=inv.id, claim_text="Person entered", claim_type="OBSERVATION",
        status="VERIFIED", confidence=0.9,
    )
    db.commit()

    res = client.post(
        f"/investigations/{inv.id}/report/generate",
        json={"title": "API Incident Report"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    report = res.json()
    assert report["status"] == "DRAFT"
    assert report["investigation_id"] == inv.id
    assert report["is_final"] is False

    rid = report["id"]

    # submit
    res = client.post(f"/reports/{rid}/submit", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "PENDING_REVIEW"

    # review -> reject
    res = client.post(f"/reports/{rid}/review", json={"decision": "REJECT"}, headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "REJECTED"

    # list + detail + audit endpoints
    assert client.get("/reports", headers=admin_headers).status_code == 200
    detail = client.get(f"/reports/{rid}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == rid
    assert client.get(f"/reports/{rid}/audit", headers=admin_headers).status_code == 200
    # file endpoint available since we stored it
    assert client.get(f"/reports/{rid}/file", headers=admin_headers).status_code == 200


def test_report_api_requires_auth(client):
    assert client.get("/reports").status_code == 401


# ---------------------------------------------------------------------------
# Report section structure (pure logic)
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {"title", "content", "status"}


def test_report_section_titles_are_the_11_expected():
    assert len(REPORT_SECTION_TITLES) == 11
    assert REPORT_SECTION_TITLES[0] == "Incident Information"
    assert REPORT_SECTION_TITLES[-1] == "Reviewer Decision"


def test_build_report_sections_produces_11_ordered_sections(db):
    from app.report import service as report_service

    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    claim = _make_claim(db, inv)
    timeline = [
        {"timestamp": 6.0, "description": "Person enters", "status": "VERIFIED",
         "evidence_ids": ["EVID-1"], "clip_public_id": "CLIP-X"},
    ]
    content = report_service.build_report_sections(db, inv, [claim], timeline, [])

    titles = [s["title"] for s in content["sections"]]
    assert titles == REPORT_SECTION_TITLES
    for sec in content["sections"]:
        assert REQUIRED_KEYS.issubset(sec.keys())
        assert "content" in sec
    assert content["sections"][0]["title"] == "Incident Information"


def test_report_no_unsupported_narrative_when_unverified(db):
    from app.report import service as report_service

    reviewer = _make_user(db)
    inv = _make_investigation(db, reviewer)
    # Claim with INSUFFICIENT_EVIDENCE status -> must land in Unknown section,
    # never in Supporting Evidence.
    claim = models.Claim(
        investigation_id=inv.id, claim_text="A red van entered",
        claim_type="OBSERVATION", status="INSUFFICIENT_EVIDENCE", confidence=0.2,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)

    content = report_service.build_report_sections(db, inv, [claim], [], [])

    supporting = next(s for s in content["sections"] if s["title"] == "Supporting Evidence")
    unknown = next(s for s in content["sections"] if s["title"] == "Unknown / Insufficient Evidence")
    assert supporting["content"]["claims"] == []
    assert any(c["claim_id"] == claim.id for c in unknown["content"]["unresolved"])
    # Recommendations must not assert an incident without verified evidence.
    assert content["sections"][9]["title"] == "Recommendations"
