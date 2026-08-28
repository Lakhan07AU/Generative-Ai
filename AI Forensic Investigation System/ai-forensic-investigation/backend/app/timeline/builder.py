"""Timeline builder (Part 3).

Builds an evidence-backed chronological timeline from events + detections, and
can persist those events against an investigation. Every event carries:
  * timestamp        (source-authoritative)
  * description
  * status           (VERIFIED / PARTIALLY_VERIFIED / INFERRED / UNVERIFIED)
  * evidence_ids     (traceable evidence references)

Events are always sorted chronologically.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import models
from app.agents import evidence_repo as repo
from app.agents.evidence_repo import clip_evidence_id


def build_timeline(
    db: Session,
    investigation_id: Optional[int] = None,
    video_id: Optional[int] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """Return an evidence-backed chronological timeline (not persisted)."""
    entries = repo.build_timeline(
        db, video_id=video_id, start_time=start_time, end_time=end_time,
        limit=limit or settings.VERIFICATION_MAX_TIMELINE_EVENTS,
    )
    for e in entries:
        e["investigation_id"] = investigation_id
    return entries


def persist_timeline(db: Session, investigation_id: int, entries: list[dict]) -> list[dict]:
    """Replace the investigation's timeline events with the given entries."""
    db.query(models.TimelineEvent).filter(
        models.TimelineEvent.investigation_id == investigation_id
    ).delete()
    db.flush()
    stored = []
    for e in entries:
        if e.get("timestamp") is None:
            continue
        row = models.TimelineEvent(
            investigation_id=investigation_id,
            timestamp=e["timestamp"],
            description=e["description"],
            status=e.get("status", "UNVERIFIED"),
            evidence_ids=json.dumps(e.get("evidence_ids") or []),
        )
        db.add(row)
        stored.append(row)
    db.commit()
    for row in stored:
        db.refresh(row)
    return stored


def load(db: Session, investigation_id: int) -> list[dict]:
    """Load the investigation's persisted timeline, sorted chronologically."""
    rows = (
        db.query(models.TimelineEvent)
        .filter(models.TimelineEvent.investigation_id == investigation_id)
        .order_by(models.TimelineEvent.timestamp.asc())
        .all()
    )
    return [
        {
            "id": r.id,
            "investigation_id": r.investigation_id,
            "timestamp": r.timestamp,
            "description": r.description,
            "status": r.status,
            "evidence_ids": json.loads(r.evidence_ids) if r.evidence_ids else [],
            "created_at": r.created_at,
        }
        for r in rows
    ]
