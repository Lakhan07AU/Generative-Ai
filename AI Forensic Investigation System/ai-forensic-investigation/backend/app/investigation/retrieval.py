"""Hybrid forensic retrieval (Phase 6).

Combines:
  * Qdrant semantic search over indexed evidence payloads (with a metadata
    ``where`` filter that hard-scopes the result to the investigation's cameras),
  * a PostgreSQL metadata query over the same evidence rows (authoritative
    provenance data, always available even when the vector index is stale).

Both paths are bounded by ``RAG_TOP_K`` and merged/deduped by evidence id.
Multi-camera isolation is enforced at the boundary: retrieval only ever sees the
camera scope passed in by the API layer - evidence from cameras outside that
scope can never be returned.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.ai.embeddings import embeddings
from app.ai.qdrant_service import qdrant
from app.core.config import settings
from app.database.models import Camera, ForensicEvidence
from app.evidence.schemas import parse_metadata
from app.rag.video_rag import ENTITY_ALIASES


def build_where(parsed, camera_ids: List[int]) -> Optional[Dict[str, Any]]:
    where: Dict[str, Any] = {"camera_id": {"$in": list(camera_ids)}}
    if parsed.event_type_hints:
        where["event_type"] = {"$in": parsed.event_type_hints}
    if parsed.tracking_id:
        where["tracking_id"] = {"$eq": parsed.tracking_id}
    if parsed.object_class:
        where["object_class"] = {"$eq": parsed.object_class}
    temporal = parsed.temporal
    if temporal.get("start") is not None:
        where.setdefault("timestamp", {})["$gte"] = float(temporal["start"])
    if temporal.get("end") is not None:
        where.setdefault("timestamp", {})["$lte"] = float(temporal["end"])
    return where


def _payload_to_candidate(hit: dict, matched_by: str) -> dict:
    payload = hit.get("payload") or {}
    return {
        "evidence_id": payload.get("evidence_id"),
        "evidence_type": payload.get("evidence_type"),
        "source": payload.get("source"),
        "camera_id": payload.get("camera_id"),
        "session_id": payload.get("session_id"),
        "timestamp": payload.get("timestamp"),
        "event_id": payload.get("event_id"),
        "event_type": payload.get("event_type"),
        "tracking_id": payload.get("tracking_id"),
        "object_class": payload.get("object_class"),
        "frame_sequence": payload.get("frame_sequence"),
        "vlm_observation_id": payload.get("vlm_observation_id"),
        "storage_path": payload.get("storage_path"),
        "sha256": payload.get("sha256"),
        "source_text": payload.get("source_text") or "",
        "vector_score": float(hit.get("score") or 0.0),
        "matched_by": matched_by,
    }


def _row_to_candidate(row: ForensicEvidence) -> dict:
    meta = parse_metadata(row)
    label = (meta.get("label") or "").strip().lower() or None
    return {
        "evidence_id": row.public_id,
        "evidence_type": row.evidence_type,
        "source": row.source,
        "camera_id": row.camera_id,
        "session_id": row.session_id,
        "timestamp": row.frame_timestamp,
        "event_id": row.event_id,
        "event_type": row.event_type,
        "tracking_id": row.tracking_id,
        "object_class": label,
        "frame_sequence": row.frame_sequence,
        "vlm_observation_id": row.vlm_observation_id,
        "storage_path": row.storage_path,
        "sha256": row.sha256,
        "source_text": row.content_text or "",
        "vector_score": None,
        "matched_by": "postgres",
    }


def _object_class_matches(candidate: dict, object_class: str) -> bool:
    cls = (candidate.get("object_class") or "").strip().lower()
    aliases = ENTITY_ALIASES.get(object_class, {object_class})
    if cls == object_class:
        return True
    text = (candidate.get("source_text") or "").lower()
    return any(a in text for a in aliases)


def _semantic_candidates(db, query_text: str, parsed, camera_ids: List[int]) -> List[dict]:
    if not camera_ids:
        return []
    vec = embeddings.embed_text(query_text)
    where = build_where(parsed, camera_ids)
    limit = settings.RAG_TOP_K * 2
    out = []
    hits = qdrant.search_evidence(list(vec), limit=limit, where=where)
    out.extend(_payload_to_candidate(h, "qdrant") for h in hits)

    # Loose pass for object-class queries: exact-label filtering would drop
    # VLM observations whose grounded text *describes* the object without a
    # tracker label. Such candidates must still be eligible.
    if parsed.object_class and not parsed.tracking_id:
        loose = dict(where)
        loose.pop("object_class", None)
        loose_hits = qdrant.search_evidence(list(vec), limit=limit, where=loose)
        for h in loose_hits:
            cand = _payload_to_candidate(h, "qdrant_semantic")
            if cand.get("evidence_id") and _object_class_matches(cand, parsed.object_class):
                out.append(cand)
    return out


def _pg_candidates(db, parsed, camera_ids: List[int], limit: int) -> List[dict]:
    q = db.query(ForensicEvidence).filter(
        ForensicEvidence.camera_id.in_(camera_ids),
        ForensicEvidence.index_status.in_(("INDEXED", "PENDING", "FAILED")),
        ForensicEvidence.frame_timestamp.isnot(None),
    )
    temporal = parsed.temporal
    if parsed.tracking_id:
        q = q.filter(ForensicEvidence.tracking_id == parsed.tracking_id)
    if parsed.event_type_hints:
        q = q.filter(ForensicEvidence.event_type.in_(parsed.event_type_hints))
    if temporal.get("start") is not None:
        q = q.filter(ForensicEvidence.frame_timestamp >= float(temporal["start"]))
    if temporal.get("end") is not None:
        q = q.filter(ForensicEvidence.frame_timestamp <= float(temporal["end"]))
    rows = q.order_by(ForensicEvidence.captured_at.desc()).limit(limit).all()
    candidates = [_row_to_candidate(r) for r in rows]
    if parsed.object_class and not parsed.tracking_id:
        candidates = [c for c in candidates if _object_class_matches(c, parsed.object_class)]
    return candidates


def retrieve_investigation_evidence(
    db,
    query_text: str,
    parsed,
    camera_ids: List[int],
    limit: Optional[int] = None,
) -> List[dict]:
    """Return merged evidence candidates bounded to ``camera_ids``."""
    camera_ids = [int(c) for c in camera_ids]
    limit = int(limit or settings.RAG_TOP_K)

    semantic = _semantic_candidates(db, query_text, parsed, camera_ids)
    pg = _pg_candidates(db, parsed, camera_ids, limit)
    if parsed.tracking_id:
        # Hard metadata match for a specific track outranks everything.
        semantic = [c for c in semantic if (c.get("tracking_id") or "") == parsed.tracking_id]

    merged: Dict[str, dict] = {}
    for c in semantic:
        if c.get("evidence_id"):
            merged[c["evidence_id"]] = c
    for c in pg:
        cid = c.get("evidence_id")
        if cid and cid not in merged:
            merged[cid] = c
    return list(merged.values())[: limit * 3]


def camera_names(db, camera_ids: List[int]) -> Dict[int, str]:
    if not camera_ids:
        return {}
    rows = db.query(Camera).filter(Camera.id.in_(camera_ids)).all()
    return {c.id: c.camera_name for c in rows}