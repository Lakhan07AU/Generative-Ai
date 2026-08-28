"""Part 4 - structured incident report generation.

Builds an 11-section incident report from a completed investigation:

  1. Incident Information
  2. Executive Summary
  3. Incident Classification
  4. Verified Timeline
  5. Observed Persons/Objects
  6. Supporting Evidence
  7. Policy Assessment
  8. Inferred Information
  9. Unknown / Insufficient Evidence
  10. Recommendations
  11. Reviewer Decision

The report is grounded strictly in persisted investigation data: claims (with
their verifications and evidence links), timeline events and policy sections.
No unsupported narrative is generated. If a claim is not verified it is listed
under "Unknown / Insufficient Evidence" rather than asserted.

The report content (JSON) is stored alongside a rendered file. Rendering uses
ReportLab for a real PDF when available and falls back to a UTF-8 markdown
file otherwise. The file is uploaded to MinIO and its path recorded.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import models
from app.schemas.report import REPORT_SECTION_TITLES
from app.storage.service import storage

logger = logging.getLogger(__name__)

VERIFIED_STATES = {"VERIFIED", "APPROVED"}
PARTIAL_STATES = {"PARTIALLY_VERIFIED", "UNCERTAIN"}
NEGATIVE_STATES = {"REJECTED", "REFUTED", "FALSE", "CONTRADICTED"}

REPORT_VERSION = 1


# ---------------------------------------------------------------------------
# Data gathering (always grounded in persisted rows)
# ---------------------------------------------------------------------------


def _claim_evidence(claim: models.Claim) -> List[dict]:
    return [
        {
            "claim_id": claim.id,
            "evidence_id": link.clip.public_id if link.clip else None,
            "clip_id": link.clip_id,
            "clip_public_id": link.clip.public_id if link.clip else None,
            "video_id": link.clip.video_id if link.clip else None,
            "timestamp": link.timestamp,
            "evidence_type": link.evidence_type,
            "relevance_score": link.relevance_score,
        }
        for link in (claim.evidence_links or [])
    ]


def _claim_last_verification(claim: models.Claim) -> Optional[models.Verification]:
    if not claim.verifications:
        return None
    return sorted(claim.verifications, key=lambda v: v.created_at or datetime.min)[-1]


def _claim_is_verified(claim: models.Claim) -> bool:
    ver = _claim_last_verification(claim)
    if ver and ver.result in VERIFIED_STATES:
        return True
    return claim.status in VERIFIED_STATES


def _format_ts(seconds: Optional[float]) -> Optional[str]:
    if seconds is None:
        return None
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _section_incident_information(inv: models.Investigation, report_title: str) -> dict:
    video = inv.video
    duration = _format_ts(video.duration_seconds) if video else None
    return {
        "title": "Incident Information",
        "content": {
            "report_title": report_title,
            "investigation_id": inv.id,
            "investigation_title": inv.title,
            "investigation_query": inv.query,
            "description": inv.description,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "video_id": video.id if video else None,
            "video_filename": video.filename if video else None,
            "video_camera": video.camera.camera_name if video and video.camera else None,
            "video_duration_seconds": duration,
            "report_generated_at": datetime.utcnow().isoformat(),
        },
        "status": "INFORMATION",
    }


def _section_executive_summary(inv: models.Investigation, claims: List[models.Claim], timeline: List[dict]) -> dict:
    verified = [c for c in claims if _claim_is_verified(c)]
    partial = [c for c in claims if not _claim_is_verified(c) and _last_status(c) in PARTIAL_STATES]
    negative = [c for c in claims if _last_status(c) in NEGATIVE_STATES]
    summary = (
        f"The investigation identified {len(verified)} verified claim(s) supported by "
        f"video evidence, {len(partial)} partially-supported claim(s), "
        f"{len(negative)} refuted claim(s) and {len(timeline)} timeline event(s). "
    )
    if not verified:
        summary += "No claim met the verification threshold; no incident is asserted."
    else:
        summary += "Verified claims are listed in section 6 (Supporting Evidence)."
    return {
        "title": "Executive Summary",
        "content": {"summary": summary, "verified_claims": len(verified), "timeline_events": len(timeline)},
        "status": "SUMMARY",
    }


def _last_status(claim: models.Claim) -> str:
    ver = _claim_last_verification(claim)
    if ver:
        return ver.result
    return claim.status


def _section_classification(claims: List[models.Claim]) -> dict:
    verified = [c for c in claims if _claim_is_verified(c)]
    if not verified:
        return {
            "title": "Incident Classification",
            "content": {"classification": "UNCLASSIFIED", "reason": "No verified claim to classify."},
            "status": "UNKNOWN",
        }
    types = {}
    for c in verified:
        types[c.claim_type or "OBSERVATION"] = types.get(c.claim_type or "OBSERVATION", 0) + 1
    return {
        "title": "Incident Classification",
        "content": {"classification": max(types, key=types.get), "claim_breakdown": types},
        "status": "CLASSIFIED",
    }


def _section_verified_timeline(inv: models.Investigation, timeline: List[dict]) -> dict:
    verified_events = [e for e in timeline if e.get("status") in VERIFIED_STATES or e.get("status", "UNVERIFIED") != "UNVERIFIED"]
    return {
        "title": "Verified Timeline",
        "content": {
            "events": [
                {
                    "timestamp": _format_ts(e.get("timestamp")),
                    "seconds": e.get("timestamp"),
                    "description": e.get("description"),
                    "status": e.get("status"),
                    "evidence_ids": e.get("evidence_ids", []),
                    "clip_public_id": e.get("clip_public_id"),
                }
                for e in sorted(verified_events, key=lambda x: x.get("timestamp") or 0)
            ]
        },
        "status": "TIMELINE",
    }


def _section_observed(inv: models.Investigation, claims: List[models.Claim]) -> dict:
    # Gather observed persons/objects from verified claims' detections via evidence links.
    observed: Dict[str, List[str]] = {}
    for c in claims:
        if not _claim_is_verified(c):
            continue
        for link in (c.evidence_links or []):
            if not link.clip:
                continue
            for d in link.clip.detections:
                label = d.label or "unknown"
                if d.tracking_id:
                    entry = f"{label} ({d.tracking_id})"
                else:
                    entry = label
                if entry not in observed:
                    observed[entry] = []
                observed[entry].append(link.clip.public_id)
    return {
        "title": "Observed Persons/Objects",
        "content": {
            "observations": [
                {"subject": k, "source_clips": sorted(set(v))} for k, v in observed.items()
            ]
        },
        "status": "OBSERVED",
    }


def _section_supporting_evidence(claims: List[models.Claim]) -> dict:
    rows = []
    for c in claims:
        if not _claim_is_verified(c):
            continue
        ver = _claim_last_verification(c)
        rows.append({
            "claim_id": c.id,
            "claim_text": c.claim_text,
            "claim_type": c.claim_type,
            "status": c.status,
            "timestamp": _format_ts(c.evidence_links[0].timestamp if c.evidence_links else None),
            "evidence_ids": [l.clip_public_id for l in (c.evidence_links or []) if l.clip_public_id],
            "verification_result": ver.result if ver else c.status,
            "verification_reason": ver.reason if ver else None,
            "evidence_links": _claim_evidence(c),
        })
    return {
        "title": "Supporting Evidence",
        "content": {"claims": rows},
        "status": "EVIDENCE",
    }


def _section_policy_assessment(inv: models.Investigation, policy_sections: List[dict]) -> dict:
    return {
        "title": "Policy Assessment",
        "content": {
            "policy_sections": [
                {
                    "score": p.get("score"),
                    "document_name": p.get("document_name"),
                    "section": p.get("section"),
                    "page": p.get("page"),
                    "text": p.get("text"),
                    "policy_id": p.get("policy_id"),
                }
                for p in policy_sections
            ]
        },
        "status": "POLICY" if policy_sections else "NO_POLICY",
    }


def _section_inferred(claims: List[models.Claim]) -> dict:
    inferred = [
        {
            "claim_id": c.id,
            "claim_text": c.claim_text,
            "claim_type": c.claim_type,
            "status": _last_status(c),
        }
        for c in claims
        if c.claim_type == "INFERENCE"
    ]
    return {
        "title": "Inferred Information",
        "content": {"inferred": inferred},
        "status": "INFERRED" if inferred else "NONE",
    }


def _section_unknown(claims: List[models.Claim]) -> dict:
    unresolved = []
    for c in claims:
        status = _last_status(c)
        if status in VERIFIED_STATES:
            continue
        unresolved.append({
            "claim_id": c.id,
            "claim_text": c.claim_text,
            "status": status,
            "reason": (_claim_last_verification(c).reason if _claim_last_verification(c) else None),
        })
    return {
        "title": "Unknown / Insufficient Evidence",
        "content": {"unresolved": unresolved},
        "status": "UNKNOWN" if unresolved else "NONE",
    }


def _section_recommendations(claims: List[models.Claim]) -> dict:
    recs = []
    if not any(_claim_is_verified(c) for c in claims):
        recs.append("Re-capture or retrieve additional footage before drawing conclusions.")
    unresolved = [c for c in claims if not _claim_is_verified(c)]
    if unresolved:
        recs.append("Manually review the flagged evidence clips to resolve uncertain claims.")
    recs.append("An authorised human reviewer must approve the final report before any action is taken.")
    return {
        "title": "Recommendations",
        "content": {"recommendations": recs},
        "status": "RECOMMENDATIONS",
    }


def _section_reviewer_decision(decisions: List[dict]) -> dict:
    return {
        "title": "Reviewer Decision",
        "content": {
            "decisions": [
                {
                    "claim_id": d.get("claim_id"),
                    "action": d.get("action"),
                    "original_text": d.get("original_text"),
                    "edited_text": d.get("edited_text"),
                    "note": d.get("note"),
                }
                for d in decisions
            ]
        },
        "status": "PENDING_REVIEW",
    }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _policy_sections_for_investigation(db: Session, inv: models.Investigation) -> List[dict]:
    """Return policy sections referenced by the investigation's findings (if any)."""
    rows = (
        db.query(models.Finding)
        .filter(models.Finding.video_id == inv.video_id, models.Finding.finding_type == "policy_assessment")
        .limit(10)
        .all()
    )
    sections: List[dict] = []
    for f in rows:
        if f.policy:
            sections.append(
                {
                    "policy_id": f.policy.id,
                    "document_name": f.policy.document_name,
                    "section": None,
                    "page": None,
                    "text": f.description or "",
                    "score": None,
                }
            )
    return sections


def build_report_sections(
    db: Session,
    inv: models.Investigation,
    claims: List[models.Claim],
    timeline: List[dict],
    review_decisions: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Assemble the full 11-section report as an ordered dict."""
    report_title = f"Incident Report — {inv.title}"
    policy_sections = _policy_sections_for_investigation(db, inv)
    decisions = review_decisions or []

    sections = [
        _section_incident_information(inv, report_title),
        _section_executive_summary(inv, claims, timeline),
        _section_classification(claims),
        _section_verified_timeline(inv, timeline),
        _section_observed(inv, claims),
        _section_supporting_evidence(claims),
        _section_policy_assessment(inv, policy_sections),
        _section_inferred(claims),
        _section_unknown(claims),
        _section_recommendations(claims),
        _section_reviewer_decision(decisions),
    ]
    return {
        "report_title": report_title,
        "version": REPORT_VERSION,
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_markdown(report: Dict[str, Any]) -> str:
    lines = [f"# {report['report_title']}", ""]
    for sec in report["sections"]:
        lines.append(f"## {sec['title']}", "")
        content = sec["content"]

        def dump(obj, depth=0):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, (list, dict)):
                        lines.append(f"{'-' * (depth + 1)} **{k}**:")
                        dump(v, depth + 1)
                    else:
                        lines.append(f"{'-' * (depth + 1)} **{k}:** {v}")
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, (list, dict)):
                        dump(item, depth + 1)
                    else:
                        lines.append(f"{'-' * (depth + 1)} {item}")
            else:
                lines.append(str(obj))

        if not content:
            lines.append("_No data._")
        else:
            dump(content)
        lines.append("")
    return "\n".join(lines)


def _render_pdf(report: Dict[str, Any]) -> bytes:
    """Render a real PDF using ReportLab. Raises if reportlab is unavailable."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        Preformatted,
    )
    from reportlab.lib import colors

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=18 * mm, leftMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=report["report_title"],
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ReportTitle", parent=styles["Title"], fontSize=16, spaceAfter=10)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#0f172a"))
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9, leading=12)
    mono = ParagraphStyle("Mono", parent=styles["Code"], fontSize=8, leading=11)

    story = [Paragraph(report["report_title"], title_style)]
    for sec in report["sections"]:
        story.append(Paragraph(sec["title"], h2))
        content = sec["content"]
        if not content:
            story.append(Paragraph("<i>No data.</i>", body))
            continue
        rows = _flatten_to_items(content)
        for row in rows:
            item = _make_inline(row)
            story.append(Paragraph(f"<br/>{item}", body))
        story.append(Spacer(1, 4))

    doc.build(story)
    return buffer.getvalue()


def _flatten_to_items(content) -> List[tuple]:
    items: List[tuple] = []

    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}{k}"
                if isinstance(v, (list, dict)):
                    walk(v, key + " / ")
                else:
                    items.append((key, v))
        elif isinstance(obj, list):
            for idx, v in enumerate(obj):
                if isinstance(v, (list, dict)):
                    walk(v, prefix)
                else:
                    items.append((prefix.rstrip(" / "), v))
        else:
            items.append((prefix.rstrip(" / "), obj))

    walk(content)
    return items


def _make_inline(row: tuple) -> str:
    key, val = row
    if key:
        return f"<b>{_esc(key)}:</b> {_esc(str(val))}"
    return _esc(str(val))


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_report(report: Dict[str, Any], renderer: Optional[str] = None) -> tuple[bytes, str]:
    """Render report to bytes + format. Prefers PDF; falls back to markdown."""
    fmt = (renderer or settings.REPORT_RENDERER or "reportlab").lower()
    if fmt == "reportlab":
        try:
            return _render_pdf(report), "pdf"
        except Exception as exc:  # noqa: BLE001
            logger.warning("ReportLab unavailable, falling back to markdown: %s", exc)
    return _render_markdown(report).encode("utf-8"), "markdown"


# ---------------------------------------------------------------------------
# Persistence + generation entry point
# ---------------------------------------------------------------------------


def generate_report(
    db: Session,
    investigation_id: int,
    user_id: Optional[int] = None,
    title: Optional[str] = None,
) -> models.Report:
    """Generate (or regenerate) a structured incident report for an investigation.

    If a DRAFT report already exists for the investigation it is updated in
    place (same row); otherwise a new report is created in DRAFT state.
    """
    inv = db.query(models.Investigation).filter(models.Investigation.id == investigation_id).first()
    if inv is None:
        raise ValueError("Investigation not found")

    claims = (
        db.query(models.Claim)
        .filter(models.Claim.investigation_id == investigation_id)
        .order_by(models.Claim.created_at.asc())
        .all()
    )
    timeline = (
        db.query(models.TimelineEvent)
        .filter(models.TimelineEvent.investigation_id == investigation_id)
        .order_by(models.TimelineEvent.timestamp.asc())
        .all()
    )
    timeline_dicts = [
        {
            "timestamp": t.timestamp,
            "description": t.description,
            "status": t.status,
            "evidence_ids": json.loads(t.evidence_ids) if t.evidence_ids else [],
            "clip_public_id": None,
        }
        for t in timeline
    ]

    decisions = []
    report = (
        db.query(models.Report)
        .filter(
            models.Report.investigation_id == investigation_id,
            models.Report.status == "DRAFT",
            models.Report.is_final == False,  # noqa: E712
        )
        .order_by(models.Report.updated_at.desc())
        .first()
    )
    if report is None:
        report = models.Report(
            investigation_id=investigation_id,
            title=(title or f"Incident Report — {inv.title}"),
            status="DRAFT",
            is_final=False,
            version=1,
            generated_by_user_id=user_id,
        )
        db.add(report)
    else:
        report.title = title or report.title
        report.generated_by_user_id = user_id
        report.version = (report.version or 1) + 1
        if title:
            report.title = title
        decisions = [
            {
                "claim_id": d.claim_id,
                "action": d.action,
                "original_text": d.original_text,
                "edited_text": d.edited_text,
                "note": d.note,
            }
            for d in report.review_decisions
        ]

    content = build_report_sections(db, inv, claims, timeline_dicts, decisions)
    db.flush()

    data, fmt = render_report(content)
    object_name = storage.unique_name(f"report-{report.id or 'new'}", f".{fmt}")
    storage_path = storage.put_bytes(
        "reports", data, object_name, content_type=("application/pdf" if fmt == "pdf" else "text/markdown")
    )

    report.content = json.dumps(content)
    report.storage_path = storage_path
    report.file_format = fmt
    report.status = "DRAFT"
    db.add(report)
    db.commit()
    db.refresh(report)

    from app.audit.service import record_audit

    record_audit(
        db, "report_generated", user_id=user_id,
        entity_type="report", entity_id=report.id,
        details=f"investigation_id={investigation_id} report_id={report.id} format={fmt}",
    )
    return report
