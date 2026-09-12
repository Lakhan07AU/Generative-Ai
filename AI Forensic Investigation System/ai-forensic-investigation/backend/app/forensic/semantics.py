"""Phase 8 forensic semantics: controlled vocabulary and careful-language guards.

Classifications never upgrade: an entry grounded only in derived evidence or
non-observed VLM text stays INFERRED/UNVERIFIED and can never become OBSERVED.
"""

from __future__ import annotations

from typing import Dict, List, Optional

OBSERVED = "OBSERVED"
INFERRED = "INFERRED"
UNKNOWN = "UNKNOWN"
CONFLICTING = "CONFLICTING"
UNVERIFIED = "UNVERIFIED"

VERIFIED = "VERIFIED"
PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
UNVERIFIED_STATUS = "UNVERIFIED"
CONTRADICTED = "CONTRADICTED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

CLASSIFICATIONS = (OBSERVED, INFERRED, UNKNOWN, CONFLICTING, UNVERIFIED)
VERIFICATION_STATUSES = (VERIFIED, PARTIALLY_VERIFIED, UNVERIFIED_STATUS, CONTRADICTED, INSUFFICIENT_EVIDENCE)

EVENT_VERBS: Dict[str, str] = {
    "object_entered": "entering",
    "object_exited": "exiting",
    "object_stopped": "stopping",
    "object_moved": "moving",
    "object_started": "starting to move",
    "prolonged_presence": "remaining present",
}

EVENT_LABELS: Dict[str, str] = {
    "object_entered": "Object entered view",
    "object_exited": "Object exited view",
    "object_stopped": "Object stopped",
    "object_moved": "Object moved",
    "object_started": "Object started moving",
    "prolonged_presence": "Prolonged presence",
}

WITHIN_VIEW_NOTE = "The event is limited to the camera's field of view; activity outside that coverage is not observed by this evidence."

IDENTITY_NOTE = "No identity was observed; the available evidence does not attribute identity to any tracked object."

CAUSAL_NOTE = "Temporal order alone does not establish causation. This finding does not assert a causal link."

QUALITY_FLAGS = ("OCCLUDED", "LOW_RESOLUTION", "BLURRED", "PARTIALLY_VISIBLE", "INSUFFICIENT_VIEW")
QUALITY_KEYWORDS: Dict[str, List[str]] = {
    "OCCLUDED": ("occluded", "occluding", "obscured", "hiding behind"),
    "BLURRED": ("blurred", "out of focus", "motion blur"),
    "PARTIALLY_VISIBLE": ("partially visible", "partially hidden", "partly visible"),
    "INSUFFICIENT_VIEW": ("too far", "out of frame", "not in frame", "outside view"),
}

CAREFUL_PREFIXES = (
    "The evidence shows",
    "The available evidence indicates",
    "The tracking system recorded",
    "The available evidence is insufficient",
    "VLM observation",
)

OBSERVED_PREFIX = "[OBSERVED]"


def revert_observed_guard(text: Optional[str]) -> bool:
    """True when a VLM statement is a literal groundable observation."""
    return bool(text and text.strip().startswith(OBSERVED_PREFIX))


def classify_with_guard(text: Optional[str]) -> str:
    """Map a VLM statement to a classification without ever upgrading it."""
    if not text or not text.strip():
        return UNKNOWN
    stripped = text.strip()
    if stripped.startswith(OBSERVED_PREFIX):
        return OBSERVED
    lowered = stripped.lower()
    for marker in ("is believed", "suggests", "appears", "likely", "probably", "may be"):
        if marker in lowered:
            return INFERRED
    return UNKNOWN


def quality_flags_of(row, low_resolution_px: int) -> List[str]:
    """Detect quality flags for a single evidence row (never modifies it)."""
    flags: List[str] = []
    text = str(getattr(row, "content_text", "") or "").lower()
    for flag, keywords in QUALITY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            flags.append(flag)
    from app.forensic.timestamps import resolution_of

    resolution = resolution_of(row)
    if resolution:
        side = max(resolution["width"], resolution["height"])
        if side < max(0, int(low_resolution_px)):
            flags.append("LOW_RESOLUTION")
    return flags


def describe_event(event_type: Optional[str], object_class: Optional[str], track_id: Optional[str], camera_name: Optional[str], clock: str) -> str:
    label = EVENT_LABELS.get(event_type or "", (event_type or "event").replace("_", " "))
    subject = object_class or "an object"
    if track_id:
        subject = f"{subject} ({track_id})"
    base = f"The tracking system recorded {subject} - {label}."
    where = f" at camera {camera_name}" if camera_name else ""
    return f"{base} {where} at {clock}."