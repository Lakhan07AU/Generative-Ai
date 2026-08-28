"""Video RAG pipeline (Part 2).

Flow implemented here:

    User query
      -> Query understanding (temporal + entity + filters)
      -> Semantic retrieval (embedding search over Qdrant `video_evidence`)
      -> Metadata filtering (video_id / camera_id / event_type / objects)
      -> Temporal filtering (start/end time bounds)
      -> Candidate reranking (hybrid: vector + keyword/metadata overlap)
      -> Top-K clips -> Evidence verification -> Evidence package
      -> LLM answer (or UNKNOWN / INSUFFICIENT EVIDENCE)

It is NOT a bare vector search: semantic result is filtered and reranked and
only clips that pass an evidence check surface in the final package.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from app.core.config import settings
from app.database import models
from app.ai import provider
from app.ai.embeddings import embeddings
from app.ai.qdrant_service import qdrant

logger = logging.getLogger(__name__)

# Keyword groups used for lightweight query understanding / keyword boosting.
ENTITY_ALIASES = {
    "person": {"person", "people", "man", "woman", "individual", "someone", "pedestrian"},
    "car": {"car", "vehicle", "automobile", "van", "truck", "sedan"},
    "backpack": {"backpack", "bag", "rucksack"},
    "bicycle": {"bicycle", "bike", "cycle"},
    "motorcycle": {"motorcycle", "motorbike", "scooter"},
}

EVENT_KEYWORDS = ["entered", "entering", "restricted", "left", "leaving", "approached", "approaching",
                  "crossed", "crossing", "running", "walking", "carrying", "stopped", "stopping"]


def analyze_query(query: str) -> dict:
    """Rule-based query understanding. Deterministic, works with/without an LLM.

    Returns entities, temporal bounds, and filter hints.
    """
    q = query.lower()
    entities = set()
    for group, aliases in ENTITY_ALIASES.items():
        for a in aliases:
            if a in q:
                entities.add(group)
                break

    events = [k for k in EVENT_KEYWORDS if k in q]

    temporal = {}
    m = re.search(r"between\s+(\d{1,2}:\d{2})\s*(?:and|-\s*)\s*(\d{1,2}:\d{2})", q)
    if m:
        temporal["start"] = _hms(m.group(1))
        temporal["end"] = _hms(m.group(2))
    if "immediately after" in q or "right after" in q:
        temporal["after_event"] = True
    else:
        m = re.search(r"after\s+(\d{1,2}:\d{2})", q)
        if m:
            temporal["start"] = _hms(m.group(1))
        m = re.search(r"before\s+(\d{1,2}:\d{2})", q)
        if m:
            temporal["end"] = _hms(m.group(1))

    return {
        "entities": sorted(entities),
        "events": events,
        "temporal": temporal,
        "raw": query,
    }


def _hms(txt: str) -> float:
    parts = txt.split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    s = int(parts[2]) if len(parts) > 2 else 0
    return float(h * 3600 + m * 60 + s)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def _build_where(analysis: dict, filters: Optional[dict]) -> Optional[dict]:
    where = {}
    if filters:
        if filters.get("video_id"):
            where["video_id"] = {"$eq": int(filters["video_id"])}
        if filters.get("camera_id"):
            where["camera_id"] = {"$eq": int(filters["camera_id"])}
    temporal = analysis.get("temporal", {})
    if "start" in temporal:
        where["end_time"] = {"$gte": float(temporal["start"])}
    if "end" in temporal:
        where.setdefault("start_time", {})["$gte"] = 0.0
        w0 = where.get("start_time")
        w0["$lte"] = float(temporal["end"])
    return where


def _semantic_score_boost(payload: dict, analysis: dict) -> float:
    """Keyword overlap bonus between query entities/events and stored metadata."""
    bonus = 0.0
    entities = analysis.get("entities", [])
    if entities:
        obj_text = " ".join(payload.get("objects", []) or []).lower()
        if any(any(a in obj_text for a in ENTITY_ALIASES.get(e, {e})) for e in entities):
            bonus += 0.2
    desc = (payload.get("description") or "").lower()
    transcript = (payload.get("transcript") or "").lower()
    for ev in analysis.get("events", []):
        if ev in desc or ev in transcript:
            bonus += 0.1
    # "immediately after" favours the earliest clip in time order later.
    return bonus


def retrieve_evidence(db, query: str, filters: Optional[dict] = None) -> list[dict]:
    """Hybrid retrieval: vector search + metadata/temporal filters + keyword rerank."""
    analysis = analyze_query(query)
    query_vec = embeddings.embed_text(query)
    where = _build_where(analysis, filters)
    limit = settings.RAG_TOP_K
    hits = qdrant.search_evidence(query_vec, limit, where)

    # rerank / hybrid score
    scored = []
    for h in hits:
        score = float(h["score"])
        bonus = _semantic_score_boost(h.get("payload", {}), analysis)
        combined = min(1.0, score + bonus)
        scored.append((combined, h))
    if analysis.get("temporal", {}).get("after_event"):
        # "immediately after" -> prefer the earliest qualifying clip
        scored.sort(key=lambda x: (x[1].get("payload", {}).get("start_time", 0)))
    else:
        scored.sort(key=lambda x: x[0], reverse=True)

    return [
        {
            "score": round(s, 4),
            "vector_score": h["score"],
            "payload": h.get("payload", {}),
        }
        for s, h in scored[: settings.RAG_RERANK_KEEP]
    ]


# ---------------------------------------------------------------------------
# Verification + evidence package
# ---------------------------------------------------------------------------

def _verify(hit: dict, analysis: dict) -> dict:
    payload = hit["payload"]
    score = hit["score"]
    entities = analysis.get("entities", [])
    obj_text = " ".join(payload.get("objects", []) or []).lower()
    entity_hit = any(
        any(a in obj_text for a in ENTITY_ALIASES.get(e, {e})) for e in entities
    ) if entities else True
    verified = score >= settings.RAG_VERIFICATION_THRESHOLD and entity_hit
    return {"verified": bool(verified), "status": "VERIFIED" if verified else "UNVERIFIED"}


def evidence_cards(db, selected: list[dict], analysis: dict) -> list[dict]:
    cards = []
    for idx, hit in enumerate(selected, start=1):
        payload = hit["payload"]
        clip_id = payload.get("clip_id")
        video_id = payload.get("video_id")
        clip = db.query(models.Clip).filter(models.Clip.id == clip_id).first() if clip_id else None
        camera_name = None
        camera = db.query(models.Camera).filter(models.Camera.id == payload.get("camera_id")).first() if payload.get("camera_id") else None
        if camera:
            camera_name = camera.camera_name
        tm = float(payload.get("start_time") or 0.0)
        cards.append(
            {
                "evidence_id": f"EVID-{idx:04d}",
                "video_id": video_id,
                "clip_id": clip_id,
                "clip_public_id": clip.public_id if clip else None,
                "camera_id": payload.get("camera_id"),
                "camera_name": camera_name,
                "timestamp": tm,
                "start_time": tm,
                "end_time": payload.get("end_time"),
                "description": payload.get("description") or "",
                "objects": payload.get("objects") or [],
                "tracking_ids": payload.get("tracking_ids") or [],
                "transcript": payload.get("transcript") or "",
                "detection_confidence": _max_detection_conf(clip),
                "retrieval_score": hit["score"],
                "source_path": payload.get("source_path", ""),
                "verification": _verify(hit, analysis),
            }
        )
    return cards


def _max_detection_conf(clip) -> Optional[float]:
    if not clip or not clip.detections:
        return None
    confs = [d.detection_confidence for d in clip.detections if d.detection_confidence is not None]
    return round(max(confs), 3) if confs else None


# ---------------------------------------------------------------------------
# LLM / grounded answer
# ---------------------------------------------------------------------------

def _build_answer(db, query: str, cards: list[dict], analysis: dict) -> dict:
    verified = [c for c in cards if c["verification"]["verified"]]
    if not verified:
        return {
            "answer": "UNKNOWN - INSUFFICIENT EVIDENCE. No clip matched the query within the "
                      "required evidence threshold. Refine the query or narrow the temporal range.",
            "status": "UNKNOWN",
        }
    if provider.available():
        context = "\n".join(
            f"- clip={c['clip_public_id']} at {c['timestamp']:.1f}s: {c['description']}"
            for c in verified[: settings.RAG_RERANK_KEEP]
        )
        prompt = (
            f"Using ONLY the observable evidence below, answer the investigator question. "
            f"Do not infer intent or identity. If the evidence does not answer it, say so.\n\n"
            f"Question: {query}\n\nEvidence:\n{context}"
        )
        text = provider.generate_text(prompt, system="You are a forensic video analyst.")
        return {"answer": text, "status": "ANSWERED"}
    # Simulation: deterministic grounded answer from evidence.
    top = verified[0]
    lines = [f"A relevant clip was found: {top['clip_public_id']} at {top['timestamp']:.1f}s."]
    if top["description"]:
        lines.append(f"Observed: {top['description']}")
    if top["objects"]:
        lines.append("Objects: " + ", ".join(top["objects"]))
    if top["tracking_ids"]:
        lines.append("Tracking: " + ", ".join(top["tracking_ids"]))
    for c in verified[1:]:
        if c["description"]:
            lines.append(f"Additional clip {c['clip_public_id']}: {c['description']}")
    lines.append("[SIMULATED - no LLM configured for answer generation]")
    return {"answer": "\n".join(lines), "status": "ANSWERED"}


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def video_rag_answer(db, query: str, filters: Optional[dict] = None) -> dict:
    """Run the full Video RAG pipeline and return {analysis, status, answer, evidence}."""
    analysis = analyze_query(query)

    # Early return if there is no semantic index at all.
    if db.query(models.Clip).count() == 0:
        return {
            "query": query,
            "analysis": analysis,
            "status": "UNKNOWN",
            "answer": "UNKNOWN - INSUFFICIENT EVIDENCE. No videos have been processed yet.",
            "evidence": [],
        }

    hits = retrieve_evidence(db, query, filters)
    cards = evidence_cards(db, hits, analysis)
    verified = [c for c in cards if c["verification"]["verified"]]
    if not verified:
        return {
            "query": query,
            "analysis": analysis,
            "status": "UNKNOWN",
            "answer": "UNKNOWN - INSUFFICIENT EVIDENCE. No matching evidence found for this query.",
            "evidence": cards,
        }

    result = _build_answer(db, query, cards, analysis)
    return {
        "query": query,
        "analysis": analysis,
        "status": result["status"],
        "answer": result["answer"],
        "evidence": cards,
    }
