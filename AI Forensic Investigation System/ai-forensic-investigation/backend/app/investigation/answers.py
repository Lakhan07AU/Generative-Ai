"""Grounded answer builder (Phase 6).

Turns reranked evidence cards into a deterministic, grounded answer. Rules:

  * Identity / intent / outside-view questions are UNANSWERABLE by design and
    return the fixed UNKNOWN responses (never fabricated).
  * With no verified evidence the answer is UNKNOWN - INSUFFICIENT EVIDENCE.
  * Otherwise the answer is assembled ONLY from observed evidence fields
    (camera, event type, tracking id, object class, timestamps).
  * VLM-derived statements are only surfaced when their stored content is
    classified OBSERVED; INFERRED stays a limitation note.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.core.config import settings
from app.investigation.query_parser import (
    COUNT,
    IDENTITY,
    INTENT,
    OUTSIDE_VIEW,
    PRESENCE,
    TRACK_HISTORY,
    WHAT,
    ParsedQuery,
    unanswerable_answer,
)

_LIMITATIONS_BASE = [
    "Object classes come from detector labels; identity and intent are never inferred from footage.",
    "Evidence timestamps are session-relative seconds; no client-supplied timestamps are trusted.",
    "Observations are grounded as OBSERVED / INFERRED / UNKNOWN; only OBSERVED statements are cited.",
]

_LIMITATION_BY_TYPE = {
    COUNT: "Counts reflect distinct evidence records/tracks, not unique individuals.",
    PRESENCE: "Presence is reported per recorded event, not per frame.",
    TRACK_HISTORY: "Track timeline is limited to events captured on camera.",
}


def _hms(seconds: float) -> str:
    seconds = int(max(0.0, float(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _fmt_ts(ts) -> str:
    if isinstance(ts, (int, float)):
        return f"{float(ts):.1f}s ({_hms(ts)})"
    return str(ts)


def _camera_label(candidate: dict, camera_names: Dict[int, str]) -> str:
    cid = candidate.get("camera_id")
    name = camera_names.get(cid) if cid is not None else None
    return f"camera {name or cid}" if cid is not None else "camera n/a"


def _lines_for(candidate: dict, camera_names: Dict[int, str]) -> List[str]:
    parts = [f"evidence {candidate.get('evidence_id')}"]
    parts.append(f"type={candidate.get('evidence_type')}")
    if candidate.get("event_type"):
        parts.append(f"event={candidate.get('event_type')}")
    cam = _camera_label(candidate, camera_names)
    parts.append(cam)
    if candidate.get("timestamp") is not None:
        parts.append(f"at={_fmt_ts(candidate.get('timestamp'))}")
    if candidate.get("tracking_id"):
        parts.append(f"track={candidate.get('tracking_id')}")
    if candidate.get("object_class"):
        parts.append(f"class={candidate.get('object_class')}")
    return parts


def build_answer(
    query_text: str,
    parsed: ParsedQuery,
    candidates: List[dict],
    camera_ids: List[int],
    camera_names: Dict[int, str],
) -> Dict[str, Any]:
    fixed = unanswerable_answer(parsed)
    filtered = [c for c in candidates if c.get("evidence_id")]
    verified = [c for c in filtered if c.get("verified")]

    # --- unanswerable intents keep an empty evidence context -----------------
    if fixed is not None:
        return {
            "query": query_text,
            "status": "UNKNOWN",
            "answer": fixed,
            "confidence": 0.0,
            "results": [],
            "sources": _sources(camera_ids, camera_names, 0),
            "limitations": _limitations(parsed),
            "analysis": _analysis(parsed, reason="unanswerable_question"),
        }

    if not filtered:
        return {
            "query": query_text,
            "status": "UNKNOWN",
            "answer": (
                "UNKNOWN - INSUFFICIENT EVIDENCE. No evidence matches this query "
                "within the searched cameras."
            ),
            "confidence": 0.0,
            "results": [],
            "sources": _sources(camera_ids, camera_names, 0),
            "limitations": _limitations(parsed),
            "analysis": _analysis(parsed, reason="no_evidence"),
        }

    if not verified:
        return {
            "query": query_text,
            "status": "UNKNOWN",
            "answer": (
                "UNKNOWN - INSUFFICIENT EVIDENCE. Candidates were found but none "
                "passed the evidence verification threshold."
            ),
            "confidence": 0.0,
            "results": _cards_from(filtered, camera_names),
            "sources": _sources(camera_ids, camera_names, len(filtered)),
            "limitations": _limitations(parsed),
            "analysis": _analysis(parsed, reason="below_threshold"),
        }

    cards = _cards_from(verified, camera_names)
    answer = _compose_answer(parsed, verified, camera_names)
    confidence = _confidence(verified)
    return {
        "query": query_text,
        "status": "ANSWERED",
        "answer": answer,
        "confidence": confidence,
        "results": cards,
        "sources": _sources(camera_ids, camera_names, len(verified)),
        "limitations": _limitations(parsed),
        "analysis": _analysis(parsed, reason="answered", evidence_count=len(verified)),
    }


def _compose_answer(parsed: ParsedQuery, verified: List[dict], camera_names: Dict[int, str]) -> str:
    cls = parsed.object_class or "object"
    t0 = parsed.temporal.get("start")
    t1 = parsed.temporal.get("end")
    window = ""
    if t0 is not None and t1 is not None:
        window = f" between {_fmt_ts(t0)} and {_fmt_ts(t1)}"
    elif t0 is not None:
        window = f" after {_fmt_ts(t0)}"
    elif t1 is not None:
        window = f" before {_fmt_ts(t1)}"

    if parsed.question_type == PRESENCE:
        n = len(verified)
        cam_names = sorted({_camera_label(c, camera_names) for c in verified})
        head = (
            f"YES - {n} recorded event(s) matched the query for '{cls}'{window} "
            f"on {', '.join(cam_names) or 'the searched cameras'}."
        )
    elif parsed.question_type == COUNT:
        tracks = {c.get("tracking_id") for c in verified if c.get("tracking_id")}
        n_tracks = len(tracks) or len(verified)
        head = (
            f"OBSERVED - {n_tracks} distinct evidence record(s)/track(s) matched "
            f"'{cls}'{window}."
        )
    elif parsed.question_type == TRACK_HISTORY and parsed.tracking_id:
        tid = parsed.tracking_id
        n = len(verified)
        earliest = min((c.get("timestamp") for c in verified if c.get("timestamp") is not None), default=None)
        latest = max((c.get("timestamp") for c in verified if c.get("timestamp") is not None), default=None)
        span = ""
        if earliest is not None and latest is not None:
            span = f" spanning {_fmt_ts(earliest)} .. {_fmt_ts(latest)}"
        head = (
            f"Track {tid} (class '{cls or 'object'}') has {n} recorded evidence "
            f"event(s){span} on {_camera_label(verified[0], camera_names)}."
        )
    else:
        head = (
            f"OBSERVED - {len(verified)} evidence record(s) matched the query "
            f"for '{cls}'{window}."
        )

    lines = [head, ""]
    for c in verified[: settings.RAG_MAX_CONTEXT_ITEMS]:
        lines.append("  - " + " | ".join(_lines_for(c, camera_names)))
    stmts = _observed_statements(verified)
    if stmts:
        lines.append("")
        lines.append("Grounded observation: " + stmts[0])
    return "\n".join(lines)


def _observed_statements(verified: List[dict]) -> List[str]:
    out = []
    for c in verified:
        tokens = []
        for token in (c.get("source_text") or "").split():
            if token.startswith("[OBSERVED]"):
                continue
            tokens.append(token)
        text = " ".join(tokens).strip()
        if text:
            out.append(text[:300])
    return out


def _confidence(verified: List[dict]) -> float:
    scores = [float(c.get("score") or 0.0) for c in verified]
    avg = (sum(scores) / len(scores)) if scores else 0.0
    return round(float(min(0.99, 0.5 + 0.1 * len(verified) + 0.3 * avg)), 2)


def _cards_from(verified: List[dict], camera_names: Dict[int, str]) -> List[Dict[str, Any]]:
    cards = []
    for rank, c in enumerate(verified[: settings.RAG_MAX_CONTEXT_ITEMS], start=1):
        cards.append(
            {
                "rank": rank,
                "evidence_id": c.get("evidence_id"),
                "evidence_type": c.get("evidence_type"),
                "source": c.get("source"),
                "camera_id": c.get("camera_id"),
                "camera_name": camera_names.get(c.get("camera_id")) if c.get("camera_id") is not None else None,
                "session_id": c.get("session_id"),
                "timestamp": c.get("timestamp"),
                "start_time": c.get("timestamp"),
                "end_time": c.get("timestamp"),
                "event_id": c.get("event_id"),
                "event_type": c.get("event_type"),
                "tracking_id": c.get("tracking_id"),
                "object_class": c.get("object_class"),
                "vlm_observation_id": c.get("vlm_observation_id"),
                "storage_path": c.get("storage_path"),
                "sha256": c.get("sha256"),
                "content_text": (c.get("source_text") or "")[:500],
                "retrieval_score": c.get("score"),
                "reasons": c.get("reasons") or [],
                "verified": bool(c.get("verified")),
            }
        )
    return cards


def _sources(camera_ids: List[int], camera_names: Dict[int, str], evidence_count: int) -> Dict[str, Any]:
    return {
        "camera_ids": [int(c) for c in camera_ids],
        "camera_names": {str(k): v for k, v in camera_names.items()},
        "evidence_count": int(evidence_count),
        "context_limit": int(settings.RAG_MAX_CONTEXT_ITEMS),
        "evidence_per_event_limit": int(settings.RAG_MAX_EVIDENCE_PER_EVENT),
    }


def _limitations(parsed: ParsedQuery) -> List[str]:
    out = list(_LIMITATIONS_BASE)
    extra = _LIMITATION_BY_TYPE.get(parsed.question_type)
    if extra:
        out.append(extra)
    if parsed.temporal.get("after_event"):
        out.append("'immediately after' is answered by ordering evidence temporally, not by causal inference.")
    return out


def _analysis(parsed: ParsedQuery, reason: str, evidence_count: int = 0) -> Dict[str, Any]:
    return {
        "question_type": parsed.question_type,
        "entities": list(parsed.entities),
        "object_class": parsed.object_class,
        "events": list(parsed.events),
        "event_type_hints": list(parsed.event_type_hints),
        "temporal": dict(parsed.temporal),
        "tracking_id": parsed.tracking_id,
        "unanswerable": bool(parsed.unanswerable),
        "reason": reason,
        "evidence_count": int(evidence_count),
    }