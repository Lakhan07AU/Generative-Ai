"""Part 4 - Evidence workspace API.

Aggregates, for human review, a unified view of every claim and its evidence:

  Claim -> Status -> Evidence -> Timestamp -> Source clip
        -> Verification result -> Policy reference

Also lists all available evidence (clips) for browsing.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database import models
from app.auth.deps import get_current_user

router = APIRouter(prefix="/evidence", tags=["evidence"])


def _clip_verification(claim: models.Claim) -> dict | None:
    if not claim.verifications:
        return {"result": claim.status, "reason": None}
    ver = sorted(claim.verifications, key=lambda v: v.created_at or datetime.min)[-1]
    checks = ver.checks
    if isinstance(checks, str):
        try:
            checks = json.loads(checks)
        except json.JSONDecodeError:
            checks = None
    return {
        "result": ver.result,
        "reason": ver.reason,
        "verifier_version": ver.verifier_version,
        "checks": checks,
    }


def _policy_references(db: Session, video_id: int | None) -> list[dict]:
    if video_id is None:
        return []
    rows = (
        db.query(models.Finding)
        .filter(
            models.Finding.video_id == video_id,
            models.Finding.finding_type == "policy_assessment",
            models.Finding.policy_id.isnot(None),
        )
        .limit(5)
        .all()
    )
    refs = []
    for r in rows:
        refs.append(
            {
                "finding_id": r.id,
                "policy_id": r.policy_id,
                "document_name": r.policy.document_name if r.policy else None,
                "description": r.description,
                "status": r.finding_status,
            }
        )
    return refs


def _build_evidence_row(db: Session, claim: models.Claim) -> dict:
    links = []
    video_id = None
    for link in (claim.evidence_links or []):
        clip = link.clip
        if clip and video_id is None:
            video_id = clip.video_id
        links.append(
            {
                "evidence_id": link.id,
                "clip_id": link.clip_id,
                "clip_public_id": clip.public_id if clip else None,
                "video_id": clip.video_id if clip else None,
                "timestamp": link.timestamp,
                "evidence_type": link.evidence_type,
                "relevance_score": link.relevance_score,
                "source_clip": (
                    {
                        "id": clip.id,
                        "public_id": clip.public_id,
                        "start_time": clip.start_time,
                        "end_time": clip.end_time,
                        "storage_path": clip.storage_path,
                    }
                    if clip
                    else None
                ),
            }
        )

    return {
        "claim_id": claim.id,
        "investigation_id": claim.investigation_id,
        "claim_text": claim.claim_text,
        "claim_type": claim.claim_type,
        "status": claim.status,
        "confidence": claim.confidence,
        "created_at": claim.created_at,
        "evidence": links,
        "verification": _clip_verification(claim),
        "policy_references": _policy_references(db, video_id),
    }


@router.get("/claims")
def list_evidence_claims(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    claims = (
        db.query(models.Claim)
        .order_by(models.Claim.created_at.desc())
        .limit(200)
        .all()
    )
    return [_build_evidence_row(db, c) for c in claims]


@router.get("/clips")
def list_evidence_clips(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    video_id: int | None = None,
):
    q = db.query(models.Clip)
    if video_id:
        q = q.filter(models.Clip.video_id == video_id)
    clips = q.order_by(models.Clip.start_time.asc()).limit(200).all()
    return [
        {
            "id": c.id,
            "public_id": c.public_id,
            "video_id": c.video_id,
            "camera_id": c.camera_id,
            "camera_name": c.camera.camera_name if c.camera else None,
            "start_time": c.start_time,
            "end_time": c.end_time,
            "description": c.clip_description.summary if c.clip_description else c.description,
            "storage_path": c.storage_path,
            "detections": [
                {
                    "id": d.id,
                    "label": d.label,
                    "timestamp": d.timestamp,
                    "tracking_id": d.tracking_id,
                    "detection_confidence": d.detection_confidence,
                }
                for d in c.detections
            ],
        }
        for c in clips
    ]
