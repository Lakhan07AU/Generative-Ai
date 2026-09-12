"""Phase 8 persistence for forensic analyses, timeline rows and reports."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.database import models
from app.investigator.store import loads_json


def _dumps(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def persist_analysis(db: Session, run: models.InvestigationRun, analysis: Dict[str, Any], user_id: Optional[int]) -> models.ForensicAnalysis:
    existing = (
        db.query(models.ForensicAnalysis)
        .filter(models.ForensicAnalysis.run_id == run.id)
        .first()
    )
    if existing:
        db.query(models.ForensicTimelineEvent).filter(
            models.ForensicTimelineEvent.run_id == run.id
        ).delete(synchronize_session=False)
        existing.summary = analysis.get("summary")
        existing.timeline = _dumps(analysis.get("timeline") or [])
        existing.findings = _dumps(analysis.get("findings") or [])
        existing.correlations = _dumps(analysis.get("correlations") or [])
        existing.contradictions = _dumps(analysis.get("contradictions") or [])
        existing.gaps = _dumps(analysis.get("gaps") or {})
        existing.relationships = _dumps(analysis.get("relationships") or [])
        existing.multi_camera = _dumps(analysis.get("multi_camera") or [])
        existing.sources = _dumps(analysis.get("sources") or [])
        existing.metrics = _dumps(analysis.get("metrics") or {})
        existing.status = "PENDING_REVIEW"
        existing.created_by_user_id = user_id
        existing.updated_at = datetime.utcnow()
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    row = models.ForensicAnalysis(
        run_id=run.id,
        investigation_id=run.investigation_id,
        summary=analysis.get("summary"),
        timeline=_dumps(analysis.get("timeline") or []),
        findings=_dumps(analysis.get("findings") or []),
        correlations=_dumps(analysis.get("correlations") or []),
        contradictions=_dumps(analysis.get("contradictions") or []),
        gaps=_dumps(analysis.get("gaps") or {}),
        relationships=_dumps(analysis.get("relationships") or []),
        multi_camera=_dumps(analysis.get("multi_camera") or []),
        sources=_dumps(analysis.get("sources") or []),
        metrics=_dumps(analysis.get("metrics") or {}),
        status="PENDING_REVIEW",
        created_by_user_id=user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def load_analysis(db: Session, run_id: int) -> Optional[Dict[str, Any]]:
    row = (
        db.query(models.ForensicAnalysis)
        .filter(models.ForensicAnalysis.run_id == run_id)
        .first()
    )
    if row is None:
        return None
    return {
        "id": row.id,
        "run_id": row.run_id,
        "investigation_id": row.investigation_id,
        "summary": row.summary,
        "status": row.status,
        "timeline": loads_json(row.timeline, []),
        "findings": loads_json(row.findings, []),
        "correlations": loads_json(row.correlations, []),
        "contradictions": loads_json(row.contradictions, []),
        "gaps": loads_json(row.gaps, {}),
        "relationships": loads_json(row.relationships, []),
        "multi_camera": loads_json(row.multi_camera, []),
        "sources": loads_json(row.sources, []),
        "metrics": loads_json(row.metrics, {}),
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def set_analysis_reviewed(db: Session, run_id: int) -> None:
    row = (
        db.query(models.ForensicAnalysis)
        .filter(models.ForensicAnalysis.run_id == run_id)
        .first()
    )
    if row is not None:
        row.status = "REVIEWED"
        row.updated_at = datetime.utcnow()
        db.add(row)
        db.commit()


def persist_timeline_rows(db: Session, run_id: int, investigation_id: int, entries: List[Dict[str, Any]], analytics_time: Optional[datetime] = None) -> None:
    for entry in entries:
        db.add(
            models.ForensicTimelineEvent(
                run_id=run_id,
                investigation_id=investigation_id,
                timeline_event_id=entry.get("timeline_event_id"),
                timestamp=entry.get("timestamp"),
                end_timestamp=entry.get("end_timestamp"),
                camera_id=entry.get("camera_id"),
                session_id=entry.get("session_id"),
                event_id=entry.get("event_id"),
                track_id=entry.get("track_id"),
                object_class=entry.get("object_class"),
                event_type=entry.get("event_type"),
                description=entry.get("description"),
                classification=entry.get("classification"),
                confidence=entry.get("confidence"),
                source=entry.get("source"),
                verification_status=entry.get("verification_status"),
                evidence_ids=_dumps(entry.get("evidence_ids") or []),
                quality_flags=_dumps(entry.get("quality_flags") or []),
                analytics_time=analytics_time,
            )
        )
    db.commit()


def load_timeline_rows(db: Session, run_id: int) -> List[Dict[str, Any]]:
    rows = (
        db.query(models.ForensicTimelineEvent)
        .filter(models.ForensicTimelineEvent.run_id == run_id)
        .order_by(models.ForensicTimelineEvent.timestamp.asc())
        .all()
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "timeline_event_id": r.timeline_event_id,
                "timestamp": r.timestamp,
                "end_timestamp": r.end_timestamp,
                "camera_id": r.camera_id,
                "session_id": r.session_id,
                "event_id": r.event_id,
                "track_id": r.track_id,
                "object_class": r.object_class,
                "event_type": r.event_type,
                "description": r.description,
                "classification": r.classification,
                "confidence": r.confidence,
                "source": r.source,
                "verification_status": r.verification_status,
                "evidence_ids": loads_json(r.evidence_ids, []),
                "quality_flags": loads_json(r.quality_flags, []),
            }
        )
    return out


def add_finding_review(
    db: Session,
    *,
    run_id: int,
    investigation_id: int,
    finding_id: str,
    action: str,
    comment: Optional[str],
    finding_snapshot: Dict[str, Any],
    reviewer_user_id: int,
) -> Dict[str, Any]:
    row = models.FindingReview(
        run_id=run_id,
        investigation_id=investigation_id,
        finding_id=finding_id,
        action=action,
        comment=comment,
        finding_snapshot=_dumps(finding_snapshot),
        reviewer_user_id=reviewer_user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "run_id": row.run_id,
        "investigation_id": row.investigation_id,
        "finding_id": row.finding_id,
        "action": row.action,
        "comment": row.comment,
        "reviewer_user_id": row.reviewer_user_id,
        "reviewed_at": row.reviewed_at,
    }


def list_finding_reviews(db: Session, run_id: int) -> List[Dict[str, Any]]:
    rows = (
        db.query(models.FindingReview)
        .filter(models.FindingReview.run_id == run_id)
        .order_by(models.FindingReview.reviewed_at.asc())
        .all()
    )
    out = []
    for r in rows:
        reviewer_name = None
        if r.reviewer:
            reviewer_name = r.reviewer.name or r.reviewer.email
        out.append(
            {
                "id": r.id,
                "finding_id": r.finding_id,
                "action": r.action,
                "comment": r.comment,
                "reviewer_user_id": r.reviewer_user_id,
                "reviewer_name": reviewer_name,
                "finding_snapshot": loads_json(r.finding_snapshot, {}),
                "reviewed_at": r.reviewed_at,
            }
        )
    return out


def get_forensic_report(db: Session, run_id: int) -> Optional[models.ForensicReport]:
    return (
        db.query(models.ForensicReport)
        .filter(models.ForensicReport.run_id == run_id)
        .order_by(models.ForensicReport.version.desc())
        .first()
    )


def create_forensic_report(
    db: Session,
    *,
    run_id: int,
    investigation_id: int,
    title: str,
    content: Dict[str, Any],
    data: bytes,
    fmt: str,
    storage_path: str,
    user_id: Optional[int],
) -> models.ForensicReport:
    latest = get_forensic_report(db, run_id)
    version = (latest.version + 1) if latest else 1
    row = models.ForensicReport(
        run_id=run_id,
        investigation_id=investigation_id,
        title=title,
        version=version,
        content=_dumps(content),
        storage_path=storage_path,
        file_format=fmt,
        status="GENERATED",
        generated_by_user_id=user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row