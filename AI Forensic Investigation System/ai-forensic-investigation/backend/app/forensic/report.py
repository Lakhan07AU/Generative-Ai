"""Phase 8 investigation report construction and rendering.

The report is built as a machine-readable JSON document with 15 sections and
rendered to PDF (via ReportLab) or markdown through the existing Phase 3/5
report renderer. Language is guarded: findings never assert identities,
causality or activity outside camera coverage.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.database import models
from app.forensic import store, timestamps as ts
from app.investigator.store import loads_json
from app.report.service import render_report
from app.core.config import settings

SECTION_TITLES = [
    "Case Information",
    "Investigation Question",
    "Executive Summary",
    "Forensic Timeline",
    "Verified Findings",
    "Unverified Findings",
    "Conflicting Evidence",
    "Evidence Gaps",
    "Supporting Evidence",
    "VLM Observations",
    "Track Information",
    "Camera Information",
    "Limitations",
    "Reviewer Information",
    "Audit Information",
]


def _executive_summary(analysis: Dict[str, Any]) -> str:
    timeline = analysis.get("timeline") or []
    findings = analysis.get("findings") or []
    gaps = analysis.get("gaps") or {}
    contradictions = analysis.get("contradictions") or []
    observed = [f for f in findings if f.get("classification") == "OBSERVED"]
    verified = [f for f in findings if f.get("verification_status") in ("VERIFIED", "PARTIALLY_VERIFIED")]
    unverified = [f for f in findings if f.get("verification_status") == "UNVERIFIED"]
    return (
        f"This report covers {len(timeline)} reconstructed timeline events derived from {len(findings)} findings. "
        f"{len(observed)} findings are classified as directly observed. "
        f"{len(verified)} findings are sufficiently supported by the available evidence; {len(unverified)} remain unverified. "
        f"{len(contradictions)} conflicting-evidence pairs and {len(gaps.get('gaps', []))} evidence gaps were identified. "
        "The available evidence is insufficient to determine every event that occurred."
    )


def _case_information(db: Any, run: models.InvestigationRun, analysis: Dict[str, Any], investigation: models.Investigation) -> Dict[str, Any]:
    return {
        "investigation_id": investigation.id,
        "case_title": investigation.title,
        "case_status": investigation.status,
        "run_id": run.id,
        "run_status": run.status,
        "query": run.query,
        "classification": loads_json(run.classification),
        "analysis_generated_at": analysis.get("generated_at"),
        "analysis_id": analysis.get("id"),
    }


def _supporting_evidence(db: Any, evidence_used: List[Dict[str, Any]], camera_ids: List[int]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in evidence_used or []:
        public_id = item.get("evidence_id") or item.get("public_id")
        if not public_id:
            continue
        row = (
            db.query(models.ForensicEvidence)
            .filter(models.ForensicEvidence.public_id == str(public_id))
            .first()
        )
        if row is None or (camera_ids and row.camera_id is not None and row.camera_id not in camera_ids):
            continue
        out.append(
            {
                "evidence_id": row.public_id,
                "evidence_type": row.evidence_type,
                "source": row.source,
                "sha256": row.sha256,
                "storage_path": row.storage_path,
                "camera_id": row.camera_id,
                "session_id": row.session_id,
                "event_time": ts.format_hhmmss(ts.event_time_of(row)),
                "captured_at": ts.iso_utc(row.captured_at),
                "index_status": row.index_status,
                "role": item.get("role"),
            }
        )
    return out


def _vlm_observations(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    observations: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in analysis.get("timeline") or []:
        vlm_id = entry.get("vlm_observation_id")
        if not vlm_id or vlm_id in seen:
            continue
        seen.add(vlm_id)
        observations.append(
            {
                "vlm_observation_id": vlm_id,
                "timeline_event_id": entry.get("timeline_event_id"),
                "summary": entry.get("description"),
                "event_time": ts.format_hhmmss(entry.get("timestamp")),
                "classification": entry.get("classification"),
            }
        )
    return observations


def _track_information(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_track: Dict[str, Dict[str, Any]] = {}
    for entry in analysis.get("timeline") or []:
        track = entry.get("track_id")
        if not track:
            continue
        info = by_track.setdefault(
            track,
            {"track_id": track, "object_class": entry.get("object_class"), "entries": [], "cameras": []},
        )
        info["entries"].append(entry.get("timeline_event_id"))
        cam = entry.get("camera_name")
        if cam and cam not in info["cameras"]:
            info["cameras"].append(cam)
    return list(by_track.values())


def _camera_information(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_cam: Dict[str, Dict[str, Any]] = {}
    for entry in analysis.get("timeline") or []:
        cam = entry.get("camera_name")
        if not cam:
            continue
        info = by_cam.setdefault(cam, {"camera_name": cam, "camera_id": entry.get("camera_id"), "entries": []})
        info["entries"].append(entry.get("timeline_event_id"))
    return list(by_cam.values())


def _reviewer_information(db: Any, run: models.InvestigationRun) -> Dict[str, Any]:
    reviews = store.list_finding_reviews(db, run.id)
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
    run_decisions = []
    for log in run_reviews:
        reviewer_name = log.user.name if log.user else None
        run_decisions.append(
            {
                "reviewed_at": ts.iso_utc(log.created_at),
                "reviewer": reviewer_name,
                "details": log.details,
            }
        )
    return {
        "run_review_decisions": run_decisions,
        "finding_reviews": [
            {
                "finding_id": r["finding_id"],
                "action": r["action"],
                "comment": r["comment"],
                "reviewer": r["reviewer_name"],
                "reviewed_at": ts.iso_utc(r["reviewed_at"]),
            }
            for r in reviews
        ],
    }


def _audit_information(db: Any, run: models.InvestigationRun, report: Optional[models.ForensicReport]) -> List[Dict[str, Any]]:
    logs = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.entity_type.in_(("investigation", "investigation_run")),
            models.AuditLog.entity_id.in_((run.id, run.investigation_id)),
        )
        .order_by(models.AuditLog.created_at.asc())
        .limit(200)
        .all()
    )
    out = []
    for log in logs:
        out.append(
            {
                "action": log.action,
                "actor": log.user.name if log.user else None,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "details": log.details,
                "created_at": ts.iso_utc(log.created_at),
            }
        )
    if report:
        out.append(
            {
                "action": "forensic_report_generated",
                "actor": report.generated_by.name if report.generated_by else None,
                "entity_type": "forensic_report",
                "entity_id": report.id,
                "details": f"run_id={run.id} version={report.version} format={report.file_format}",
                "created_at": ts.iso_utc(report.created_at),
            }
        )
    return out


def build_report_dict(
    db: Any,
    *,
    run: models.InvestigationRun,
    investigation: models.Investigation,
    analysis: Dict[str, Any],
    evidence_used: List[Dict[str, Any]],
    camera_ids: List[int],
    report: Optional[models.ForensicReport] = None,
) -> Dict[str, Any]:
    timeline = analysis.get("timeline") or []
    findings = analysis.get("findings") or []
    contradictions = analysis.get("contradictions") or []

    verified = [
        {"finding_id": f["finding_id"], "text": f["text"], "classification": f["classification"], "verification_status": f["verification_status"], "evidence_support": f["evidence_support"]}
        for f in findings
        if f.get("verification_status") in ("VERIFIED", "PARTIALLY_VERIFIED")
    ]
    unverified = [
        {"finding_id": f["finding_id"], "text": f["text"], "verification_status": f["verification_status"], "evidence_support": f["evidence_support"]}
        for f in findings
        if f.get("verification_status") in ("UNVERIFIED", "INSUFFICIENT_EVIDENCE")
    ]

    doc: Dict[str, Any] = {
        "report_title": f"{settings.FORENSIC_REPORT_TITLE_PREFIX} - {investigation.title}",
        "report_id": report.id if report else None,
        "version": report.version if report else 1,
        "file_format": report.file_format if report else None,
        "generated_at": ts.iso_utc(report.created_at) if report else None,
        "case_information": _case_information(db, run, analysis, investigation),
        "investigation_question": run.query,
        "executive_summary": _executive_summary(analysis),
        "timeline": [
            {
                "timeline_event_id": e["timeline_event_id"],
                "time": ts.format_hhmmss(e.get("timestamp")),
                "camera": e.get("camera_name"),
                "track_id": e.get("track_id"),
                "object_class": e.get("object_class"),
                "event_type": e.get("event_type"),
                "classification": e.get("classification"),
                "verification_status": e.get("verification_status"),
                "description": e.get("description"),
                "evidence_ids": e.get("evidence_ids"),
            }
            for e in timeline
        ],
        "verified_findings": verified,
        "unverified_findings": unverified,
        "conflicting_evidence": contradictions,
        "evidence_gaps": (analysis.get("gaps") or {}),
        "supporting_evidence": _supporting_evidence(db, evidence_used, camera_ids),
        "vlm_observations": _vlm_observations(analysis),
        "track_information": _track_information(analysis),
        "camera_information": _camera_information(analysis),
        "limitations": _limitations(analysis),
        "reviewer_information": _reviewer_information(db, run),
        "audit_information": _audit_information(db, run, report),
    }
    return doc


def _limitations(analysis: Dict[str, Any]) -> List[str]:
    limits: List[str] = []
    for finding in analysis.get("findings") or []:
        for lim in finding.get("limitations") or []:
            if lim not in limits:
                limits.append(lim)
    gaps = analysis.get("gaps") or {}
    for gap in gaps.get("gaps", []):
        note = gap.get("note")
        if note and note not in limits:
            limits.append(note)
    if not limits:
        limits.append("The available evidence is limited to the covered cameras and captured instants.")
    return limits


def to_render_input(doc: Dict[str, Any]) -> Dict[str, Any]:
    sections = []
    titles = {
        "case_information": "1. Case Information",
        "investigation_question": "2. Investigation Question",
        "executive_summary": "3. Executive Summary",
        "timeline": "4. Forensic Timeline",
        "verified_findings": "5. Verified Findings",
        "unverified_findings": "6. Unverified Findings",
        "conflicting_evidence": "7. Conflicting Evidence",
        "evidence_gaps": "8. Evidence Gaps",
        "supporting_evidence": "9. Supporting Evidence",
        "vlm_observations": "10. VLM Observations",
        "track_information": "11. Track Information",
        "camera_information": "12. Camera Information",
        "limitations": "13. Limitations",
        "reviewer_information": "14. Reviewer Information",
        "audit_information": "15. Audit Information",
    }
    for key, title in titles.items():
        sections.append({"title": title, "content": doc.get(key)})
    return {"report_title": doc.get("report_title") or "Investigation Report", "sections": sections}