"""Explainable deterministic reranking (Phase 6).

Ranks merged candidates by a transparent composite score and produces per-item
human-readable reasons so every surfaced evidence record can explain *why* it
was chosen. Applies the two bounded context caps:

  * ``RAG_MAX_CONTEXT_ITEMS``   - global ceiling on context cards,
  * ``RAG_MAX_EVIDENCE_PER_EVENT`` - per-event dedup ceiling (one incident
    must not drown the whole answer in near-duplicate frames).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.investigation.query_parser import ParsedQuery
from app.rag.video_rag import ENTITY_ALIASES


def _score_candidate(candidate: dict, parsed: ParsedQuery) -> tuple[float, List[str]]:
    reasons: List[str] = []
    score = 0.0

    vector_score = candidate.get("vector_score")
    if vector_score is not None:
        score += max(0.0, min(1.0, float(vector_score)))
        reasons.append(f"semantic={vector_score:.2f}")

    text = (candidate.get("source_text") or "").lower()
    obj_class = (candidate.get("object_class") or "").strip().lower()

    if parsed.object_class:
        aliases = ENTITY_ALIASES.get(parsed.object_class, {parsed.object_class})
        if obj_class == parsed.object_class:
            score += 0.30
            reasons.append(f"object_class={obj_class}")
        elif any(a in text for a in aliases):
            score += 0.15
            reasons.append("object_mentioned_in_content")

    if parsed.tracking_id and (candidate.get("tracking_id") or "") == parsed.tracking_id:
        score += 0.40
        reasons.append(f"tracking_id={parsed.tracking_id}")

    if parsed.event_type_hints and candidate.get("event_type") in parsed.event_type_hints:
        score += 0.20
        reasons.append(f"event={candidate.get('event_type')}")

    temporal = parsed.temporal
    ts = candidate.get("timestamp")
    if isinstance(ts, (int, float)) and (temporal.get("start") is not None or temporal.get("end") is not None):
        start = temporal.get("start")
        end = temporal.get("end")
        in_window = (start is None or float(ts) >= float(start)) and (end is None or float(ts) <= float(end))
        if in_window:
            score += 0.10
            reasons.append("time_in_window")

    for ent in parsed.entities:
        aliases = ENTITY_ALIASES.get(ent, {ent})
        if any(a in text.lower() for a in aliases):
            score += 0.05
            reasons.append(f"keyword={ent}")

    return round(min(1.0, score), 4), reasons


def rerank_candidates(candidates: List[dict], parsed: ParsedQuery) -> List[dict]:
    """Return reranked evidence cards (score + reasons), capped and deduped."""
    ranked = []
    for c in candidates:
        score, reasons = _score_candidate(c, parsed)
        verified = bool(
            score >= settings.RAG_VERIFICATION_THRESHOLD
            or (c.get("vector_score") is not None and c["vector_score"] >= settings.RAG_VERIFICATION_THRESHOLD)
            or bool(parsed.tracking_id and (c.get("tracking_id") or "") == parsed.tracking_id)
            or bool(parsed.object_class and (c.get("object_class") or "") == parsed.object_class)
        )
        ranked.append(
            {
                **c,
                "score": score,
                "reasons": reasons,
                "verified": verified,
            }
        )

    ranked.sort(key=lambda x: (x["score"], x.get("timestamp") or 0), reverse=True)

    # per-event dedup: cap identical (event_type, tracking_id) groups.
    per_event: Dict[tuple, int] = {}
    selected: List[dict] = []
    max_per_event = int(getattr(settings, "RAG_MAX_EVIDENCE_PER_EVENT", 3))
    for c in ranked:
        key = (c.get("event_type"), c.get("tracking_id"))
        if per_event.get(key, 0) >= max_per_event:
            continue
        per_event[key] = per_event.get(key, 0) + 1
        selected.append(c)
        if len(selected) >= int(getattr(settings, "RAG_MAX_CONTEXT_ITEMS", 8)):
            break

    return selected