"""Part 4 - Human review + report generation API.

Routes:
  POST /investigations/{id}/report/generate   - generate structured report (DRAFT)
  POST /reports/{id}/submit                   - DRAFT -> PENDING_REVIEW
  POST /reports/{id}/claims/{claim_id}/review - per-claim review decision
  POST /reports/{id}/review                   - overall APPROVE / REJECT
  POST /reports/{id}/finalize                 - APPROVED -> FINAL
  GET  /reports                               - list reports
  GET  /reports/{id}                          - report detail (content + decisions)
  GET  /reports/{id}/file                     - preview / download rendered file
  GET  /reports/{id}/audit                    - audit trail for the report
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database import models
from app.schemas.report import (
    ReportDetail,
    ReportGenerateRequest,
    ReportOut,
    ReviewDecisionCreate,
    ReviewDecisionOut,
    ReportReviewOverall,
)
from app.auth.deps import get_current_user, require_roles
from app.report import service as report_service
from app.report import review as review_service
from app.storage.service import storage

router = APIRouter(tags=["reports"])


def _get_report_or_404(db: Session, report_id: int) -> models.Report:
    report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


@router.post(
    "/investigations/{investigation_id}/report/generate",
    response_model=ReportDetail,
)
def generate_report(
    investigation_id: int,
    payload: ReportGenerateRequest = ReportGenerateRequest(),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        report = report_service.generate_report(
            db, investigation_id, user_id=current_user.id, title=payload.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return report


# ---------------------------------------------------------------------------
# Workflow transitions
# ---------------------------------------------------------------------------


@router.post("/reports/{report_id}/submit", response_model=ReportOut)
def submit_for_review(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    _: models.User = Depends(require_roles("REVIEWER", "INVESTIGATOR", "ADMIN")),
):
    try:
        return review_service.submit_for_review(db, report_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reports/{report_id}/review", response_model=ReportOut)
def review_overall(
    report_id: int,
    payload: ReportReviewOverall,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    _: models.User = Depends(require_roles("REVIEWER", "ADMIN")),
):
    try:
        return review_service.review_overall(
            db, report_id, current_user.id, payload.decision, payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reports/{report_id}/finalize", response_model=ReportOut)
def finalize_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    _: models.User = Depends(require_roles("REVIEWER", "ADMIN")),
):
    try:
        return review_service.finalize_report(db, report_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Per-claim review decisions
# ---------------------------------------------------------------------------


@router.post(
    "/reports/{report_id}/claims/{claim_id}/review",
    response_model=ReviewDecisionOut,
)
def review_claim(
    report_id: int,
    claim_id: int,
    payload: ReviewDecisionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    _: models.User = Depends(require_roles("REVIEWER", "ADMIN")),
):
    req = ReviewDecisionCreate(
        claim_id=claim_id,
        action=payload.action,
        edited_text=payload.edited_text,
        note=payload.note,
    )
    try:
        return review_service.record_claim_decision(db, report_id, current_user.id, req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@router.get("/reports", response_model=list[ReportOut])
def list_reports(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Report)
        .order_by(models.Report.created_at.desc())
        .limit(100)
        .all()
    )


@router.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    report = _get_report_or_404(db, report_id)
    return report


@router.get("/reports/{report_id}/file")
def get_report_file(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    download: bool = False,
):
    report = _get_report_or_404(db, report_id)
    if not report.storage_path or not storage.exists(report.storage_path):
        raise HTTPException(status_code=404, detail="Report file not stored")
    data = storage.get_bytes(report.storage_path)
    fmt = report.file_format or "pdf"
    media_type = "application/pdf" if fmt == "pdf" else "text/markdown; charset=utf-8"
    filename = f"report-{report.id}.{fmt}"
    if download:
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    else:
        headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    return StreamingResponse(
        iter([data]),
        media_type=media_type,
        headers=headers,
    )


@router.get("/reports/{report_id}/audit")
def get_report_audit(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    _: models.User = Depends(require_roles("REVIEWER", "ADMIN")),
):
    _get_report_or_404(db, report_id)
    rows = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.entity_type == "report",
            models.AuditLog.entity_id == report_id,
        )
        .order_by(models.AuditLog.created_at.asc())
        .limit(500)
        .all()
    )
    return [
        {
            "id": r.id,
            "action": r.action,
            "user_id": r.user_id,
            "user_name": r.user.name if r.user else None,
            "details": r.details,
            "created_at": r.created_at,
        }
        for r in rows
    ]
