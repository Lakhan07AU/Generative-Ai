"""Part 4 - human-in-the-loop review workflow.

States: DRAFT -> PENDING_REVIEW -> APPROVED | REJECTED
Only APPROVED reports can become FINAL.

Per-claim actions (recorded on report_review_decisions):
  ACCEPT    - reviewer agrees with the AI claim
  REJECT    - reviewer rejects the claim
  EDIT      - reviewer edits the claim text (original AI + edited stored)
  UNCERTAIN - reviewer cannot decide (defaults to pending)

Overall report actions:
  SUBMIT    - move DRAFT -> PENDING_REVIEW
  APPROVE   - move PENDING_REVIEW -> APPROVED
  REJECT    - move PENDING_REVIEW -> REJECTED
  FINALIZE  - move APPROVED -> (is_final = True)

Every transition and every per-claim decision is written to the audit trail.
"""

from __future__ import annotations

import json
from typing import List, Optional

from sqlalchemy.orm import Session

from app.database import models
from app.audit.service import record_audit
from app.schemas.report import ReviewDecisionCreate

ALLOWED_CLAIM_ACTIONS = {"ACCEPT", "REJECT", "EDIT", "UNCERTAIN"}

VALID_STATUSES = {"DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED"}


def _get_report_or_404(db: Session, report_id: int) -> models.Report:
    report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if report is None:
        raise ValueError("Report not found")
    return report


def _audit(db: Session, user_id: Optional[int], report_id: int, action: str, details: str) -> None:
    record_audit(
        db, action, user_id=user_id,
        entity_type="report", entity_id=report_id, details=details,
    )


def record_claim_decision(
    db: Session,
    report_id: int,
    user_id: Optional[int],
    payload: ReviewDecisionCreate,
) -> models.ReviewDecision:
    report = _get_report_or_404(db, report_id)
    if report.status not in ("PENDING_REVIEW",):
        raise ValueError(
            f"Claims can only be reviewed while the report is PENDING_REVIEW (current: {report.status})"
        )

    action = payload.action.upper()
    if action not in ALLOWED_CLAIM_ACTIONS:
        raise ValueError(f"Unknown review action '{payload.action}'. Must be one of {sorted(ALLOWED_CLAIM_ACTIONS)}")
    if action == "EDIT" and not (payload.edited_text or "").strip():
        raise ValueError("EDIT requires an edited claim text")

    original_text = None
    if payload.claim_id:
        claim = db.query(models.Claim).filter(models.Claim.id == payload.claim_id).first()
        if claim:
            original_text = claim.claim_text

    decision = models.ReviewDecision(
        report_id=report_id,
        claim_id=payload.claim_id,
        action=action,
        original_text=original_text,
        edited_text=(payload.edited_text or "").strip() or None,
        note=payload.note,
        reviewer_user_id=user_id,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)

    _audit(
        db, "review_claim_decision", user_id, report_id,
        f"report_id={report_id} claim_id={payload.claim_id} action={action}",
    )
    return decision


def submit_for_review(db: Session, report_id: int, user_id: Optional[int]) -> models.Report:
    """DRAFT -> PENDING_REVIEW. Re-embeds review decisions into the content."""
    report = _get_report_or_404(db, report_id)
    if report.status != "DRAFT":
        raise ValueError(f"Only DRAFT reports can be submitted for review (current: {report.status})")
    report.status = "PENDING_REVIEW"
    db.add(report)
    db.commit()
    db.refresh(report)
    _audit(
        db, "report_submitted_for_review", user_id, report_id,
        f"report_id={report_id} -> PENDING_REVIEW",
    )
    return report


def review_overall(
    db: Session,
    report_id: int,
    user_id: Optional[int],
    decision: str,
    note: Optional[str] = None,
) -> models.Report:
    """PENDING_REVIEW -> APPROVED | REJECTED."""
    report = _get_report_or_404(db, report_id)
    if report.status != "PENDING_REVIEW":
        raise ValueError(f"Only PENDING_REVIEW reports can be approved/rejected (current: {report.status})")

    decision = decision.upper()
    if decision not in ("APPROVE", "REJECT"):
        raise ValueError("Overall decision must be APPROVE or REJECT")

    report.status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    report.reviewed_by_user_id = user_id
    db.add(report)
    db.commit()
    db.refresh(report)
    _audit(
        db, f"report_{decision.lower()}d", user_id, report_id,
        f"report_id={report_id} -> {report.status} note={note or ''}",
    )
    return report


def finalize_report(db: Session, report_id: int, user_id: Optional[int]) -> models.Report:
    """APPROVED -> FINAL (is_final=True)."""
    report = _get_report_or_404(db, report_id)
    if report.status != "APPROVED":
        raise ValueError(f"Only APPROVED reports can become FINAL (current: {report.status})")
    report.is_final = True
    db.add(report)
    db.commit()
    db.refresh(report)
    _audit(
        db, "report_finalized", user_id, report_id,
        f"report_id={report_id} is_final=True",
    )
    return report
