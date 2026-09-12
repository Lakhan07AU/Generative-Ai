"""Phase 4 VLM observation contracts.

Structured, provenance-preserving schemas for live vision observations.
Coordinate/units conventions inherited from earlier phases: every spatial value
is ABSOLUTE FRAME PIXELS. No facial recognition, names, identity, or biometric
identification is ever part of these contracts; statements are grounded as
OBSERVED / INFERRED / UNKNOWN.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class StatementClass(str, Enum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


# A tiny guardrail lexicon: statements that look like identity / intent / facial
# recognition claims are downgraded to UNKNOWN with an explanatory note. This is a
# defensive post-filter, not a substitute for the model prompt instructions.
_FORBIDDEN_SUBSTRINGS = (
    "is named ",
    "the name ",
    "license plate",
    "photograph matches ",
    "matches the suspect",
    "identity is",
    "intends to",
    "intent is",
    "wanted ",
    " face of ",
)


class VlmSourceFrame(BaseModel):
    """A provenance reference to one source frame (NEVER pixel data)."""

    frame_id: int
    sequence: int
    timestamp: float
    width: int = 0
    height: int = 0


class VlmObservationItem(BaseModel):
    """One grounded statement from a vision observation."""

    item_id: str
    statement: str
    classification: StatementClass
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    basis: List[str] = Field(default_factory=list)

    def as_broadcast(self) -> dict:
        return {
            "item_id": self.item_id,
            "statement": self.statement,
            "classification": self.classification.value,
            "confidence": self.confidence,
            "basis": list(self.basis),
        }


class VlmObservation(BaseModel):
    """A complete grounded observation attached to real source frames."""

    observation_id: str
    request_id: str
    camera_id: int
    camera_name: Optional[str] = None
    session_id: Optional[int] = None
    trigger: str = "manual"  # event | periodic | manual
    trigger_detail: Optional[str] = None
    source_frames: List[VlmSourceFrame] = Field(default_factory=list)
    window_start: Optional[float] = None
    window_end: Optional[float] = None
    summary: str = ""
    items: List[VlmObservationItem] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    model: str = ""
    provider_mode: str = "simulation"  # simulation | openai
    created_at: str = Field(default_factory=utcnow_iso)

    def as_broadcast(self) -> dict:
        return {
            "type": "vlm_observation",
            "observation_id": self.observation_id,
            "request_id": self.request_id,
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "session_id": self.session_id,
            "trigger": self.trigger,
            "trigger_detail": self.trigger_detail,
            "source_frames": [f.model_dump() for f in self.source_frames],
            "window_start": self.window_start,
            "window_end": self.window_end,
            "summary": self.summary,
            "items": [i.as_broadcast() for i in self.items],
            "notes": list(self.notes),
            "model": self.model,
            "provider_mode": self.provider_mode,
            "created_at": self.created_at,
        }

    def to_storage(self) -> dict:
        """Serialization used when persisting an observation (Phase 6)."""
        return self.model_dump()


class VlmRequest(BaseModel):
    """An accepted observation request (what the worker is about to run)."""

    request_id: str
    camera_id: int
    session_id: Optional[int] = None
    trigger: str = "manual"
    trigger_detail: Optional[str] = None
    provider_mode: str = "simulation"
    active: bool = True
    context: Dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)

    def as_broadcast(self) -> dict:
        d = self.model_dump(mode="json")
        d["type"] = "vlm_request"
        return d


class VlmMetrics(BaseModel):
    """Per-session VLM activity metrics (bounded; no pixel data)."""

    total_requests: int = 0
    total_observations: int = 0
    total_errors: int = 0
    total_retries: int = 0
    dropped_requests: int = 0
    cooldown_active: bool = False
    last_error: Optional[str] = None
    last_observation_at: Optional[str] = None
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0

    def as_broadcast(self) -> dict:
        d = self.model_dump()
        d["type"] = "vlm_metrics"
        return d


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

_OBSERVATION_LOCKS: Dict[str, threading.Lock] = {}
_observation_lock = threading.Lock()
_obs_ids: set = set()


def _unique_observation_id() -> str:
    with _observation_lock:
        while True:
            oid = new_id("obs")
            if oid not in _obs_ids:
                _obs_ids.add(oid)
                if len(_obs_ids) > 2000:
                    _obs_ids.clear()
                return oid


def coerce_statements(result: dict, max_statements: int = 32) -> List[VlmObservationItem]:
    """Turn raw provider output into validated statement items (guardrails)."""
    items: List[VlmObservationItem] = []
    downgraded: List[str] = []
    for raw in (result.get("statements") or [])[:max_statements]:
        if not isinstance(raw, dict) or "statement" not in raw:
            continue
        statement = str(raw.get("statement", "")).strip()
        if not statement:
            continue
        cls_raw = str(raw.get("classification", "")).strip().upper()
        cls = StatementClass(cls_raw) if cls_raw in StatementClass.__members__ else StatementClass.UNKNOWN
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        basis = [str(b) for b in (raw.get("basis") or []) if isinstance(b, (str, int, float))]
        lowered = statement.lower()
        if any(f in lowered for f in _FORBIDDEN_SUBSTRINGS):
            cls = StatementClass.UNKNOWN
            confidence = 0.0
            downgraded.append(statement)
        items.append(
            VlmObservationItem(
                item_id=new_id("item"),
                statement=statement,
                classification=cls,
                confidence=confidence,
                basis=basis,
            )
        )
    if not items:
        items.append(
            VlmObservationItem(
                item_id=new_id("item"),
                statement="The vision provider returned no usable statements.",
                classification=StatementClass.UNKNOWN,
                confidence=0.0,
                basis=[],
            )
        )
    return items


def build_observation(
    request: VlmRequest,
    result: Optional[dict],
    source_frames: List[VlmSourceFrame],
    window_start: Optional[float],
    window_end: Optional[float],
    camera_name: Optional[str],
) -> VlmObservation:
    """Assemble a :class:`VlmObservation` from a provider result."""
    result = result or {}
    provider_mode = str(result.get("model", "")).startswith("simulation") and "simulation" or "openai"
    if request.provider_mode == "simulation" and not str(result.get("model", "")).startswith("simulation"):
        provider_mode = request.provider_mode
    items = coerce_statements(result)
    downgraded = [
        i.statement for i in items if i.classification == StatementClass.UNKNOWN
        and i.confidence == 0.0 and not i.basis
    ]
    notes = [str(n) for n in (result.get("notes") or [])]
    if downgraded:
        notes.append("Statements that could imply identity or intent were downgraded to UNKNOWN.")
    return VlmObservation(
        observation_id=_unique_observation_id(),
        request_id=request.request_id,
        camera_id=request.camera_id,
        camera_name=camera_name,
        session_id=request.session_id,
        trigger=request.trigger,
        trigger_detail=request.trigger_detail,
        source_frames=source_frames,
        window_start=window_start,
        window_end=window_end,
        summary=str(result.get("summary", "")).strip(),
        items=items,
        notes=notes,
        model=str(result.get("model", "")),
        provider_mode=provider_mode,
    )