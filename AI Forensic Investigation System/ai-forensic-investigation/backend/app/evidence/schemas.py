"""Phase 5 evidence contracts.

Evidence is captured from a live session's tracking events and VLM
observations and persisted as durable, traceable forensic evidence. Every
spatial/temporal value is server-generated: absolute buffer timestamps and the
server capture clock. No client-supplied timestamps, identities, or intent are
ever accepted. Statements stay grounded as OBSERVED / INFERRED / UNKNOWN.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict, List, Optional


class EvidenceType(str, Enum):
    """Extensible taxonomy of captured evidence records.

    * FRAME           - a RAW_SOURCE encoded copy of a buffered source frame.
    * IMAGE           - a RAW_SOURCE image (reserved for manual captures).
    * CLIP            - a stored video clip (reserved for stored-video phase).
    * DETECTION       - a single object detection (powered by a source frame).
    * TRACK_EVENT     - a DERIVED tracking event record with its visual content.
    * VLM_OBSERVATION - a DERIVED grounded observation with its source frames.
    """

    FRAME = "FRAME"
    IMAGE = "IMAGE"
    CLIP = "CLIP"
    DETECTION = "DETECTION"
    TRACK_EVENT = "TRACK_EVENT"
    VLM_OBSERVATION = "VLM_OBSERVATION"


class EvidenceSource(str, Enum):
    RAW_SOURCE = "RAW_SOURCE"
    DERIVED = "DERIVED"


class IndexStatus(str, Enum):
    PENDING = "PENDING"
    INDEXING = "INDEXING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


def _dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _loads(raw: Optional[str], default: Any = None) -> Any:
    if not raw:
        return default if default is not None else []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


# ---------------------------------------------------------------------------
# Metadata serialisation helpers
# ---------------------------------------------------------------------------


def serialize_metadata(metadata: Dict[str, Any]) -> str:
    return _dumps(metadata or {})


def parse_metadata(row) -> Dict[str, Any]:
    # ORM column is extra_metadata (maps to DB column "metadata").
    out = _loads(getattr(row, "extra_metadata", None), {})
    if not out:
        out = _loads(getattr(row, "metadata", None), {})
    return out if isinstance(out, dict) else {}


def serialize_provenance(provenance: Dict[str, Any]) -> str:
    return _dumps(provenance or {})


def parse_provenance(row) -> Dict[str, Any]:
    out = _loads(getattr(row, "provenance", None), {})
    return out if isinstance(out, dict) else {}


def parse_source_frame_ids(row) -> List[int]:
    out = _loads(getattr(row, "source_frame_ids", None), [])
    if not isinstance(out, list):
        return []
    return [int(x) for x in out if isinstance(x, (int, float, str)) and str(x).lstrip("-").isdigit()]


# ---------------------------------------------------------------------------
# Searchable content text for evidence records
# ---------------------------------------------------------------------------


def track_event_content(event, camera_name: str) -> str:
    parts = [str(event.event_type or "").strip()]
    if event.tracking_id:
        parts.append(f"tracking_id={event.tracking_id}")
    if event.frame_index:
        parts.append(f"frame={event.frame_index}")
    if camera_name:
        parts.append(f"camera={camera_name}")
    label = (getattr(event, "metadata", None) or {}).get("label")
    if label:
        parts.append(f"label={label}")
    return " ".join(parts)


def frame_content(camera_id: int, camera_name: str, session_id: Optional[int], sequence: int) -> str:
    return f"source frame camera_id={camera_id} camera={camera_name or ''} session_id={session_id or 0} sequence={sequence}"


def observation_content(observation: Dict[str, Any]) -> str:
    parts = [str(observation.get("summary", "") or "").strip()]
    for item in (observation.get("items") or []):
        stmt = str(item.get("statement", "") or "").strip()
        if stmt:
            cls = str(item.get("classification", "UNKNOWN") or "UNKNOWN")
            parts.append(f"[{cls}] {stmt}")
    trigger = str(observation.get("trigger", "") or "").strip()
    detail = str(observation.get("trigger_detail", "") or "").strip()
    if detail:
        parts.append(f"trigger={trigger} detail={detail}")
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Qdrant payload for an evidence record
# ---------------------------------------------------------------------------


def evidence_index_payload(
    evidence_id: str,
    evidence_type: str,
    source: str,
    camera_id: Optional[int],
    session_id: Optional[int],
    timestamp: Optional[float],
    event_id: Optional[str],
    event_type: Optional[str],
    tracking_id: Optional[str],
    frame_sequence: Optional[int],
    vlm_observation_id: Optional[str],
    storage_path: Optional[str],
    sha256: Optional[str],
    source_text: str,
    object_class: Optional[str] = None,
) -> Dict[str, Any]:
    """Metadata kept on every Qdrant evidence point (searchable + traceable)."""
    return {
        "evidence_id": evidence_id,
        "evidence_type": evidence_type,
        "source": source,
        "camera_id": camera_id,
        "session_id": session_id,
        "timestamp": timestamp,
        "event_id": event_id,
        "event_type": event_type,
        "tracking_id": tracking_id,
        "object_class": (object_class or "").strip().lower() or None,
        "frame_sequence": frame_sequence,
        "vlm_observation_id": vlm_observation_id,
        "storage_path": storage_path,
        "sha256": sha256,
        "source_text": source_text[:2000],
    }


# ---------------------------------------------------------------------------
# Machine-readable provenance snapshot (server-generated)
# ---------------------------------------------------------------------------


def build_provenance(
    *,
    public_id: str,
    evidence_type: str,
    source: str,
    camera_id: Optional[int],
    session_id: Optional[int],
    event_id: Optional[str],
    event_type: Optional[str],
    tracking_id: Optional[str],
    frame_sequence: Optional[int],
    frame_timestamp: Optional[float],
    vlm_observation_id: Optional[str],
    source_frame_ids: List[int],
    window_start: Optional[float],
    window_end: Optional[float],
    captured_at: Optional[str],
    storage_path: Optional[str],
    mime_type: Optional[str],
    width: Optional[int],
    height: Optional[int],
    sha256: Optional[str],
    size_bytes: Optional[int],
) -> Dict[str, Any]:
    return {
        "evidence_id": public_id,
        "evidence_type": evidence_type,
        "source": source,
        "camera_id": camera_id,
        "session_id": session_id,
        "event_id": event_id,
        "event_type": event_type,
        "tracking_id": tracking_id,
        "frame_sequence": frame_sequence,
        "frame_timestamp": frame_timestamp,
        "vlm_observation_id": vlm_observation_id,
        "source_frame_ids": list(source_frame_ids),
        "window_start": window_start,
        "window_end": window_end,
        "captured_at": captured_at,
        "storage_path": storage_path,
        "mime_type": mime_type,
        "dimensions": {"width": width, "height": height} if width and height else None,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "generated_by": "server",
    }