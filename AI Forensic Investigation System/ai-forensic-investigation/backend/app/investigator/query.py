"""Phase 7 - deterministic investigation query classifier.

Separate from Phase 6's intent parser (which extracts retrieval constraints)
this classifier decides WHAT KIND of investigation a query starts and which tool
plan applies. It is purely rule-based and explainable: the reasons list is
persisted with the run so a human can see why the agent chose its plan.

Categories:
    UNANSWERABLE - identity / intent / outside-view (never answered)
    TRACK        - dedicated track id request (most precise)
    VLM          - "describe / what do you see" observation request
    EVIDENCE     - "show the evidence / what evidence" request
    CAMERA       - explicit camera mention
    EVENT        - single event-signal query
    OBJECT       - single object-signal query
    TEMPORAL     - single temporal-only query
    COMBINED     - several independent signals (object+event+track+temporal+camera)
    OTHER        - generic catch-all (default retrieval plan)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.investigation.query_parser import parse_query

CAT_UNANSWERABLE = "UNANSWERABLE"
CAT_TRACK = "TRACK"
CAT_VLM = "VLM"
CAT_EVIDENCE = "EVIDENCE"
CAT_CAMERA = "CAMERA"
CAT_EVENT = "EVENT"
CAT_OBJECT = "OBJECT"
CAT_TEMPORAL = "TEMPORAL"
CAT_COMBINED = "COMBINED"
CAT_OTHER = "OTHER"

_ALL_CATEGORIES = (
    CAT_UNANSWERABLE, CAT_TRACK, CAT_VLM, CAT_EVIDENCE, CAT_CAMERA,
    CAT_EVENT, CAT_OBJECT, CAT_TEMPORAL, CAT_COMBINED, CAT_OTHER,
)

_VLM_HINTS = (
    "describe", "what do you see", "what can you see", "what is happening",
    "what's happening", "what happened in", "observe", "observation",
    "tell me about", "what does the footage", "looks like", "summarize the",
)
_EVIDENCE_HINTS = (
    "evidence for", "what evidence", "show the evidence", "supporting evidence",
    "prove", "proof of", "was there evidence", "what proof",
    "do we have evidence",
)
_EVIDENCE_ID_RE = re.compile(r"\bEVD-[A-Za-z0-9_-]{2,32}\b", re.IGNORECASE)
_CAMERA_RE = re.compile(r"\bcam(?:era)?\b\s+([A-Za-z0-9][A-Za-z0-9\-_ ]{1,39})", re.IGNORECASE)
_CAMERA_STOP = {"view", "a", "the", "at", "between", "from", "and", "in", "on", "is", "of", "to"}

_TRACK_RE = re.compile(r"\b(?:TRK|T|EVD)-[A-Za-z0-9_-]+\b", re.IGNORECASE)


def _camera_hint(raw: str) -> Optional[str]:
    m = _CAMERA_RE.search(raw)
    if not m:
        return None
    hint = m.group(1).strip()
    first = hint.split(" ")[0].strip(":.!,;")
    if first.lower() in _CAMERA_STOP or len(first) < 2:
        return None
    return first


def classify_query(query: str) -> Dict[str, Any]:
    """Classify a natural-language query into a category + signals."""
    raw = (query or "").strip()
    low = raw.lower()
    parsed = parse_query(query)

    signals: List[str] = []
    reasons: List[str] = []

    tracking_id = parsed.tracking_id
    object_class = parsed.object_class
    event_type_hints = list(parsed.event_type_hints)
    temporal = dict(parsed.temporal)
    camera_hint = _camera_hint(raw)
    has_vlm = any(h in low for h in _VLM_HINTS)
    has_evidence_word = any(h in low for h in _EVIDENCE_HINTS)
    evidence_ids = _EVIDENCE_ID_RE.findall(raw)
    if has_vlm:
        signals.append("vlm")
        reasons.append("observation/description intent")
    if evidence_ids or has_evidence_word:
        signals.append("evidence")
        reasons.append("evidence-id or evidence wording")
    if tracking_id:
        signals.append("track")
        reasons.append(f"tracking_id={tracking_id}")
    if object_class:
        signals.append("object")
        reasons.append(f"object_class={object_class}")
    if event_type_hints:
        signals.append("event")
        reasons.append(f"event_hints={event_type_hints}")
    if temporal:
        signals.append("temporal")
        reasons.append(f"temporal={temporal}")
    if camera_hint:
        signals.append("camera")
        reasons.append(f"camera_hint={camera_hint}")

    category = CAT_OTHER
    if parsed.unanswerable:
        category = CAT_UNANSWERABLE
        category_reason = f"unanswerable_type={parsed.question_type}"
    elif evidence_ids:
        # Explicit EVD- references are evidence-detail requests, even though the
        # Phase 6 parser also recognises them as track-like tokens.
        category = CAT_EVIDENCE
        category_reason = f"explicit evidence id(s): {evidence_ids}"
    elif tracking_id:
        category = CAT_TRACK
        category_reason = "explicit track request"
    else:
        strong = {s for s in signals if s in ("object", "event", "temporal", "camera")}
        if len(strong) >= 2:
            category = CAT_COMBINED
            category_reason = f"multiple signals: {sorted(strong)}"
        elif camera_hint:
            category = CAT_CAMERA
            category_reason = "explicit camera mention"
        elif object_class:
            category = CAT_EVENT if event_type_hints else CAT_OBJECT
            category_reason = "event intent" if event_type_hints else "object inquiry"
        elif event_type_hints:
            category = CAT_EVENT
            category_reason = "event intent"
        elif temporal:
            category = CAT_TEMPORAL
            category_reason = "temporal-only inquiry"
        elif has_vlm:
            category = CAT_VLM
            category_reason = "observation/description intent"
        elif evidence_ids or has_evidence_word:
            category = CAT_EVIDENCE
            category_reason = "evidence inquiry"
        else:
            category = CAT_OTHER
            category_reason = "generic question"

    return {
        "category": category,
        "category_reason": category_reason,
        "question_type": parsed.question_type,
        "object_class": object_class,
        "entities": list(parsed.entities),
        "events": list(parsed.events),
        "event_type_hints": event_type_hints,
        "temporal": temporal,
        "tracking_id": tracking_id,
        "unanswerable": bool(parsed.unanswerable),
        "camera_hint": camera_hint,
        "evidence_ids": [e for e in evidence_ids],
        "signals": sorted(set(signals)),
        "reasons": reasons,
        "raw": raw,
    }