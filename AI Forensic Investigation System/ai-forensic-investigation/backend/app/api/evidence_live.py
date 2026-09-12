"""Live forensic evidence API (Phase 5).

Exposes captured forensic evidence (frames, tracking events, VLM observations)
with provenance, content bytes, index management, and vector-backed semantic
search. All routes require a LIVE role (ADMIN / SECURITY_OFFICER /
INVESTIGATOR). Evidence is server-generated only: provenance always comes from
the capture pipeline, never from clients.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.ai.embeddings import embeddings
from app.ai.qdrant_service import qdrant
from app.api.live import LIVE_ROLES
from app.auth.deps import get_current_user, require_roles
from app.core.config import settings
from app.database import models
from app.database.models import ForensicEvidence, User, VlmObservationRecord
from app.database.session import get_db
from app.evidence.indexer import evidence_indexer
from app.evidence.schemas import (
    parse_metadata,
    parse_provenance,
    parse_source_frame_ids,
)
from app.storage.service import storage

router = APIRouter(prefix="/evidence/live", tags=["evidence-live"])


def _row_out(row: "ForensicEvidence") -> dict:
    return {
        "id": row.id,
        "public_id": row.public_id,
        "evidence_type": row.evidence_type,
        "source": row.source,
        "camera_id": row.camera_id,
        "session_id": row.session_id,
        "event_id": row.event_id,
        "event_type": row.event_type,
        "tracking_id": row.tracking_id,
        "frame_sequence": row.frame_sequence,
        "frame_timestamp": row.frame_timestamp,
        "window_start": row.window_start,
        "window_end": row.window_end,
        "vlm_observation_id": row.vlm_observation_id,
        "captured_at": row.captured_at.isoformat() if row.captured_at else None,
        "storage_path": row.storage_path,
        "mime_type": row.mime_type,
        "width": row.width,
        "height": row.height,
        "sha256": row.sha256,
        "size_bytes": row.size_bytes,
        "index_status": row.index_status,
        "index_attempts": row.index_attempts,
        "index_error": row.index_error,
        "indexed_at": row.indexed_at.isoformat() if row.indexed_at else None,
    }


@router.get("")
def list_live_evidence(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
    camera_id: Optional[int] = Query(default=None),
    session_id: Optional[int] = Query(default=None),
    evidence_type: Optional[str] = Query(default=None),
    index_status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=int(settings.EVIDENCE_LIST_LIMIT)),
):
    q = db.query(ForensicEvidence)
    if camera_id is not None:
        q = q.filter(ForensicEvidence.camera_id == camera_id)
    if session_id is not None:
        q = q.filter(ForensicEvidence.session_id == session_id)
    if evidence_type:
        q = q.filter(ForensicEvidence.evidence_type == evidence_type)
    if index_status:
        q = q.filter(ForensicEvidence.index_status == index_status)
    rows = q.order_by(ForensicEvidence.captured_at.desc()).limit(limit).all()
    return [_row_out(r) for r in rows]


@router.get("/{public_id}")
def get_live_evidence(
    public_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    row = (
        db.query(ForensicEvidence)
        .filter(ForensicEvidence.public_id == public_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    observation = None
    if row.vlm_observation_id:
        obs = (
            db.query(VlmObservationRecord)
            .filter(VlmObservationRecord.observation_id == row.vlm_observation_id)
            .first()
        )
        if obs is not None:
            observation = {
                "observation_id": obs.observation_id,
                "request_id": obs.request_id,
                "trigger": obs.trigger,
                "trigger_detail": obs.trigger_detail,
                "summary": obs.summary,
                "items": obs.items,
                "notes": obs.notes,
                "model": obs.model,
                "provider_mode": obs.provider_mode,
                "source_frames": obs.source_frames,
                "window_start": obs.window_start,
                "window_end": obs.window_end,
                "created_at": obs.created_at.isoformat() if obs.created_at else None,
            }
    return {
        **_row_out(row),
        "metadata": parse_metadata(row),
        "source_frame_ids": parse_source_frame_ids(row),
        "provenance": parse_provenance(row),
        "observation": observation,
    }


@router.get("/{public_id}/content")
def get_live_evidence_content(
    public_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    row = (
        db.query(ForensicEvidence)
        .filter(ForensicEvidence.public_id == public_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if not row.storage_path or not storage.exists(row.storage_path):
        raise HTTPException(status_code=404, detail="Evidence content not stored")
    data = storage.get_bytes(row.storage_path)
    return Response(
        content=data,
        media_type=row.mime_type or "application/octet-stream",
        headers={
            "X-Evidence-Id": row.public_id,
            "X-Evidence-Sha256": row.sha256 or "",
            "Content-Disposition": f'inline; filename="{row.public_id}.jpg"',
        },
    )


@router.post("/{public_id}/reindex")
def reindex_live_evidence(
    public_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    row = (
        db.query(ForensicEvidence)
        .filter(ForensicEvidence.public_id == public_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if not evidence_indexer.submit(row.id, row.public_id):
        raise HTTPException(status_code=503, detail="Index worker unavailable")
    fresh = (
        db.query(ForensicEvidence)
        .filter(ForensicEvidence.id == row.id)
        .first()
    )
    if fresh is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return {
        **_row_out(fresh),
        "reindexed": True,
        "queue_size": evidence_indexer.queue_size,
    }


@router.post("/search")
def search_live_evidence(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
    evidence_type: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
):
    query = str(payload.get("query") or payload.get("text") or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="query is required")
    vec = embeddings.embed_text(query)
    where = None
    if evidence_type:
        where = {"evidence_type": evidence_type}
    hits = qdrant.search_evidence(list(vec), limit=limit, where=where)
    out = []
    for hit in hits:
        meta = hit.get("payload") or {}
        out.append(
            {
                "evidence_id": meta.get("evidence_id"),
                "score": round(float(hit.get("score", 0.0)) * 100, 2),
                "evidence_type": meta.get("evidence_type"),
                "source": meta.get("source"),
                "camera_id": meta.get("camera_id"),
                "session_id": meta.get("session_id"),
                "timestamp": meta.get("timestamp"),
                "event_id": meta.get("event_id"),
                "event_type": meta.get("event_type"),
                "tracking_id": meta.get("tracking_id"),
                "frame_sequence": meta.get("frame_sequence"),
                "vlm_observation_id": meta.get("vlm_observation_id"),
                "storage_path": meta.get("storage_path"),
                "sha256": meta.get("sha256"),
                "source_text": meta.get("source_text"),
            }
        )
    return {"query": query, "count": len(out), "results": out}