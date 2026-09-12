"""Deterministic rule-based investigation query parser (Phase 6).

No LLM is involved: the parser maps an investigator question to structured
constraints (entities / object class / event types / temporal bounds / track id)
plus a question intent. Everything is bounded and explainable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.rag.video_rag import ENTITY_ALIASES, EVENT_KEYWORDS

# Question intents.
PRESENCE = "PRESENCE"
COUNT = "COUNT"
WHAT = "WHAT_HAPPENED"
TRACK_HISTORY = "TRACK_HISTORY"
IDENTITY = "IDENTITY"
INTENT = "INTENT"
OUTSIDE_VIEW = "OUTSIDE_VIEW"
OTHER = "OTHER"

# Keyword -> actual detector event_type values.
EVENT_TYPE_MAP = {
    "entered": "object_entered",
    "entering": "object_entered",
    "entered the": "object_entered",
    "left": "object_exited",
    "leaving": "object_exited",
    "exited": "object_exited",
    "exiting": "object_exited",
    "stopped": "object_stopped",
    "stopping": "object_stopped",
    "moved": "object_moved",
    "moving": "object_moved",
    "disappeared": "object_disappeared",
    "reappeared": "object_reappeared",
    "presence": "prolonged_presence",
    "prolonged": "prolonged_presence",
    "entered the restricted": "object_entered",
}

# Deterministic identity / intent / outside-view signals. These questions are
# unanswerable from CCTV geometry + labels and must return UNKNOWN.
_IDENTITY_HINTS = (
    "who is",
    "who was",
    "who are",
    "name of",
    "identify",
    "identity",
    "person's name",
    "person is",
    "who is that",
    "face",
    "facial",
)
_INTENT_HINTS = (
    "intent",
    "intention",
    "intended",
    "intend",
    "intends",
    "motive",
    "why did",
    "reason for",
    "purpose of",
)
_OUTSIDE_VIEW_HINTS = (
    "outside the camera",
    "outside the camera view",
    "outside the field of view",
    "outside camera view",
    "outside the view",
    "not visible on camera",
    "not within the camera",
    "beyond the camera",
    "after the camera view ended",
)

_UNANSWERABLE_ANSWERS = {
    IDENTITY: (
        "UNKNOWN - The identity of an observed person cannot be determined from this "
        "footage. The system does not perform facial recognition and never attributes names."
    ),
    INTENT: (
        "UNKNOWN - The intention of an observed person cannot be determined from this footage. "
        "Intent is never inferred from surveillance evidence."
    ),
    OUTSIDE_VIEW: (
        "UNKNOWN - Events outside the camera view are not observable from this footage and "
        "are never inferred from evidence."
    ),
}

_ALIAS_BY_CLASS = {}
for _cls, _aliases in ENTITY_ALIASES.items():
    for _a in _aliases:
        _ALIAS_BY_CLASS[_a] = _cls


def _match_class(word: str) -> Optional[str]:
    """Map a word to an object class, tolerating simple plurals."""
    cls = _ALIAS_BY_CLASS.get(word)
    if cls:
        return cls
    if word.endswith("es") and len(word) > 3:
        cls = _ALIAS_BY_CLASS.get(word[:-2])
        if cls:
            return cls
    if word.endswith("s") and len(word) > 2:
        return _ALIAS_BY_CLASS.get(word[:-1])
    if word.endswith("ies") and len(word) > 3:
        return _ALIAS_BY_CLASS.get(word[:-3] + "y")
    return None


def _to_seconds(hms: str) -> float:
    parts = hms.split(":")
    h = int(parts[0]) if parts else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    s = int(parts[2]) if len(parts) > 2 else 0
    return float(h * 3600 + m * 60 + s)


@dataclass
class ParsedQuery:
    raw: str
    entities: List[str] = field(default_factory=list)
    object_class: Optional[str] = None
    events: List[str] = field(default_factory=list)
    event_type_hints: List[str] = field(default_factory=list)
    temporal: Dict[str, object] = field(default_factory=dict)
    tracking_id: Optional[str] = None
    question_type: str = OTHER
    unanswerable: bool = False
    unanswerable_reason: Optional[str] = None


def _detect_tracking_id(q: str) -> Optional[str]:
    # canonical demo ids: TRK-0012 ; generic: EVD-..., T-3, "tracking T-0001"
    patterns = (
        r"\bTRK-[A-Za-z0-9_-]+\b",
        r"\bT-[A-Za-z0-9_-]+\b",
        r"\bEVD-[A-Za-z0-9_-]+\b",
        r"(?:track|tracking)(?:\s+id)?[\s:=#]+([A-Za-z]{1,8}-[A-Za-z0-9_-]+)",
    )
    for pat in patterns:
        m = re.search(pat, q, flags=re.IGNORECASE)
        if m:
            return m.group(1) if m.lastindex else m.group(0)
    return None


def parse_query(query: str) -> ParsedQuery:
    raw = (query or "").strip()
    q = raw.lower()

    parsed = ParsedQuery(raw=raw)

    # ---- unanswerable intents first (identity / intent / outside view) ----
    if any(h in q for h in _OUTSIDE_VIEW_HINTS):
        parsed.question_type = OUTSIDE_VIEW
        parsed.unanswerable = True
        parsed.unanswerable_reason = "outside camera view"
        return parsed
    if any(h in q for h in _INTENT_HINTS):
        parsed.question_type = INTENT
        parsed.unanswerable = True
        parsed.unanswerable_reason = "intent cannot be inferred"
        return parsed
    if any(h in q for h in _IDENTITY_HINTS):
        parsed.question_type = IDENTITY
        parsed.unanswerable = True
        parsed.unanswerable_reason = "identity cannot be determined"
        return parsed

    # ---- question intent ----
    if any(ph in q for ph in ("how many", "number of", " how many", "count of")):
        parsed.question_type = COUNT
    elif any(ph in q for ph in ("is there", "was there", "were there", "are there", "any ", " present")):
        parsed.question_type = PRESENCE
    elif _detect_tracking_id(raw) is not None or "track" in q or "tracking" in q:
        parsed.question_type = TRACK_HISTORY
    elif any(ph in q for ph in ("what happened", "describe", "show", "find", "events", "list", "when did")):
        parsed.question_type = WHAT
    else:
        parsed.question_type = OTHER

    # ---- entities / object class ----
    entities: set = set()
    for word in re.findall(r"[a-z']+", q):
        cls = _match_class(word)
        if cls:
            entities.add(cls)
    parsed.entities = sorted(entities)
    parsed.object_class = parsed.entities[0] if parsed.entities else None

    # ---- event keywords -> concrete event_type hints ----
    seen: List[str] = []
    for kw in EVENT_KEYWORDS:
        if kw in q and EVENT_TYPE_MAP.get(kw) and EVENT_TYPE_MAP[kw] not in seen:
            parsed.events.append(kw)
            seen.append(EVENT_TYPE_MAP[kw])
            parsed.event_type_hints.append(EVENT_TYPE_MAP[kw])

    # ---- temporal bounds ----
    parsed.tracking_id = _detect_tracking_id(raw)
    temporal: Dict[str, object] = {}

    between = re.search(r"between\s+(\d{1,2}(?::\d{2}){1,2})\s*(?:and|to|-)\s*(\d{1,2}(?::\d{2}){1,2})", q)
    if between:
        temporal["start"] = _to_seconds(between.group(1))
        temporal["end"] = _to_seconds(between.group(2))
    elif any(ph in q for ph in ("immediately after", "right after", "just after")):
        temporal["after_event"] = True
        after = re.search(r"^(?:immediately\s+|right\s+|just\s+)?after\s+(\d{1,2}(?::\d{2}){1,2})$", q)
        if after:
            temporal["start"] = _to_seconds(after.group(1))
            temporal["after_event"] = False
    else:
        after = re.search(r"(?:immediately\s+|right\s+|just\s+)?after\s+(\d{1,2}(?::\d{2}){1,2})", q)
        before = re.search(r"before\s+(\d{1,2}(?::\d{2}){1,2})", q)
        at = re.search(r"\bat\s+(\d{1,2}(?::\d{2}){1,2})", q)
        if after and not before:
            temporal["start"] = _to_seconds(after.group(1))
        elif before and not after:
            temporal["end"] = _to_seconds(before.group(1))
        if at:
            t = _to_seconds(at.group(1))
            temporal["start"] = t
            temporal.setdefault("end", t + 60.0)
    parsed.temporal = temporal

    return parsed


def unanswerable_answer(parsed: ParsedQuery) -> Optional[str]:
    if not parsed.unanswerable:
        return None
    return _UNANSWERABLE_ANSWERS.get(parsed.question_type)