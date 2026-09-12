"""Phase 8 - forensic verification, timeline & reporting REST API.

Routes (all under a run):
    POST /runs/{run_id}/forensic/analyze      run the forensic pipeline
    GET  /runs/{run_id}/forensic              fetch the analysis (timeline etc.)
    POST /runs/{run_id}/findings/{fid}/review record a human finding review
    GET  /runs/{run_id}/reviews               run + finding review state
    POST /runs/{run_id}/report                generate the investigation report
    GET  /runs/{run_id}/report                latest report metadata + content
    GET  /runs/{run_id}/report/file           rendered PDF / markdown bytes

RBAC:
    * analyzing / reading a run requires a LIVE role (REVIEWER denied).
    * recording a finding review additionally accepts the REVIEWER role - the
      human review function credentials.
    * report generation requires the run to be COMPLETED.

The forensic pipeline is deterministic and read-only over the run's evidence;
it never modifies original evidence rows.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.investigator import RUN_REVIEW_ROLES, _run_or_404
from app.api.live import LIVE_ROLES
from app.audit.service import record_audit
from app.auth.deps import require_roles
from app.core.config import settings
from app.database import models
from app.database.models import Investigation, User
from app.database.session import get_db
from app.forensic import pipeline, report as report_builder, schemas, store
from app.investigator.store import COMPLETED, loads_json
from app.report.service import render_report
from app.storage.service import storage

router = APIRouter(tags=["forensics"])

ANALYZABLE_STATUSES = ("READY_FOR_REVIEW", "COMPLETED")


def _require_analysis(db: Session, run_id: int) -> Dict[str, Any]:
    analysis = store.load_analysis(db, run_id)
    if analysis is None:
        raise HTTPException(status_code=409, detail="Run must be forensically analyzed first")
    return analysis


@router.post("/runs/{run_id}/forensic/analyze", response_model=Dict[str, Any])
def analyze_run_forensic(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    run = _run_or_404(db, run_id)
    if run.status not in ANALYZABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Run is {run.status}; only {', '.join(ANALYZABLE_STATUSES)} runs can be analyzed",
        )
    investigation = db.query(Investigation).filter(Investigation.id == run.investigation_id).first()
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    from app.investigator.camera_scope import case_camera_ids

    camera_ids = case_camera_ids(db, investigation.id)
    analysis = pipeline.analyze_run(db, run, investigation, current_user.id, camera_ids=camera_ids)
    record_audit(
        db,
        "forensic_analysis_generated",
        user_id=current_user.id,
        entity_type="investigation_run",
        entity_id=run.id,
        details=f"run_id={run.id} timeline={len(analysis['timeline'])} findings={len(analysis['findings'])}",
    )
    return analysis


@router.get("/runs/{run_id}/forensic", response_model=Dict[str, Any])
def get_run_forensic(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    run = _run_or_404(db, run_id)
    analysis = store.load_analysis(db, run.id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="No forensic analysis found for this run")
    analysis["timeline_rows"] = store.load_timeline_rows(db, run.id)
    return analysis


@router.post("/runs/{run_id}/findings/{finding_id}/review", response_model=Dict[str, Any])
def review_finding(
    run_id: int,
    finding_id: str,
    payload: schemas.FindingReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*RUN_REVIEW_ROLES)),
):
    run = _run_or_404(db, run_id)
    analysis = _require_analysis(db, run.id)
    snapshot = schemas.snapshot_of_finding(analysis, finding_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"{finding_id} not found in the run analysis")

    review = store.add_finding_review(
        db,
        run_id=run.id,
        investigation_id=run.investigation_id,
        finding_id=finding_id,
        action=payload.action.value,
        comment=payload.comment,
        finding_snapshot=snapshot,
        reviewer_user_id=current_user.id,
    )
    store.set_analysis_reviewed(db, run.id)
    record_audit(
        db,
        "finding_review",
        user_id=current_user.id,
        entity_type="investigation_run",
        entity_id=run.id,
        details=f"run_id={run.id} finding={finding_id} action={payload.action.value}",
    )
    return review


@router.get("/runs/{run_id}/reviews", response_model=Dict[str, Any])
def get_run_reviews(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    run = _run_or_404(db, run_id)
    run_reviews = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.action == "investigation_run_review",
            models.AuditLog.entity_type == "investigation_run",
            models.AuditLog.entity_id == run.id,
        )
        .order_by(models.AuditLog.created_at.asc())
        .all()
    )
    return {
        "run_id": run.id,
        "run_status": run.status,
        "run_reviews": [
            {
                "decision": (log.details or "").split(" ")[0].replace("decision=", ""),
                "reviewer": log.user.name if log.user else None,
                "details": log.details,
                "created_at": log.created_at,
            }
            for log in run_reviews
        ],
        "finding_reviews": store.list_finding_reviews(db, run.id),
    }


def _render_report_file(doc: Dict[str, Any]) -> tuple[bytes, str]:
    data, fmt = render_report(report_builder.to_render_input(doc), settings.FORENSIC_REPORT_RENDERER)
    return data, fmt


@router.post("/runs/{run_id}/report", response_model=Dict[str, Any])
def generate_investigation_report(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    run = _run_or_404(db, run_id)
    if run.status != COMPLETED:
        raise HTTPException(status_code=409, detail="Reports can only be generated for COMPLETED runs")
    investigation = db.query(Investigation).filter(Investigation.id == run.investigation_id).first()
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    analysis = _require_analysis(db, run.id)

    result = loads_json(run.result, {})
    evidence_used = result.get("evidence_used") or []

    from app.investigator.camera_scope import case_camera_ids

    camera_ids = case_camera_ids(db, investigation.id)
    doc = report_builder.build_report_dict(
        db,
        run=run,
        investigation=investigation,
        analysis=analysis,
        evidence_used=evidence_used,
        camera_ids=camera_ids,
    )
    data, fmt = _render_report_file(doc)
    object_name = storage.unique_name(f"forensic-report-run-{run.id}", f".{fmt}")
    storage_path = storage.put_bytes(
        "reports",
        data,
        object_name,
        content_type=("application/pdf" if fmt == "pdf" else "text/markdown"),
    )
    report_row = store.create_forensic_report(
        db,
        run_id=run.id,
        investigation_id=run.investigation_id,
        title=doc["report_title"] or "Investigation Report",
        content=doc,
        data=data,
        fmt=fmt,
        storage_path=storage_path,
        user_id=current_user.id,
    )
    record_audit(
        db,
        "forensic_report_generated",
        user_id=current_user.id,
        entity_type="forensic_report",
        entity_id=report_row.id,
        details=f"run_id={run.id} version={report_row.version} format={fmt}",
    )
    return {
        "report_id": report_row.id,
        "run_id": run.id,
        "title": report_row.title,
        "version": report_row.version,
        "file_format": fmt,
        "storage_path": storage_path,
        "generated_at": report_row.created_at,
    }


@router.get("/runs/{run_id}/report", response_model=Dict[str, Any])
def get_investigation_report(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    run = _run_or_404(db, run_id)
    report_row = store.get_forensic_report(db, run.id)
    if report_row is None:
        raise HTTPException(status_code=404, detail="No investigation report exists for this run")
    content = loads_json(report_row.content, {})
    return {
        "report_id": report_row.id,
        "run_id": run.id,
        "title": report_row.title,
        "version": report_row.version,
        "file_format": report_row.file_format,
        "storage_path": report_row.storage_path,
        "status": report_row.status,
        "generated_at": report_row.created_at,
        "content": content,
    }


@router.get("/runs/{run_id}/report/file")
def get_investigation_report_file(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    run = _run_or_404(db, run_id)
    report_row = store.get_forensic_report(db, run.id)
    if report_row is None:
        raise HTTPException(status_code=404, detail="No investigation report exists for this run")
    if not report_row.storage_path or not storage.exists(report_row.storage_path):
        raise HTTPException(status_code=404, detail="Report file is not available")
    data = storage.get_bytes(report_row.storage_path)
    media_type = "application/pdf" if report_row.file_format == "pdf" else "text/markdown"
    filename = f"investigation-report-run-{run.id}-v{report_row.version}.{report_row.file_format}"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )