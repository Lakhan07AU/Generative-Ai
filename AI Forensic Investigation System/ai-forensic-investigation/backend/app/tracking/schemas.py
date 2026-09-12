"""Phase 3 tracking contracts - ALL UNITS ABSOLUTE FRAME PIXELS (documented).
Persistent VISUAL ids only; no facial/biometric identification.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TrackState(str, Enum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    LOST = "LOST"
    REMOVED = "REMOVED"


class TrackUpdate(BaseModel):
    session_id: str
    camera_id: str
    frame_index: int
    frame_timestamp: datetime
    tracking_id: str
    state: TrackState
    label: str = "Person"
    class_id: Optional[int] = None
    confidence: float = 0.0
    bbox: List[int] = Field(default_factory=list)
    center: Optional[List[float]] = None
    displacement_px: float = 0.0
    direction_deg: Optional[float] = None
    pixel_velocity: float = 0.0
    distance_traveled_px: float = 0.0
    stationary_seconds: float = 0.0
    moving_seconds: float = 0.0
    stationary_ratio: float = 0.0
    width_px: float = 0.0
    height_px: float = 0.0
    width_delta_px: float = 0.0
    height_delta_px: float = 0.0
    hits: int = 1
    missing: int = 0

    def as_broadcast(self) -> dict:
        d = self.model_dump()
        d["type"] = "track_update"
        d["frame_timestamp"] = self.frame_timestamp.isoformat()
        return d


class TrackingEvent(BaseModel):
    event_id: str
    event_type: str
    session_id: str = ""
    camera_id: str = ""
    frame_index: int = 0
    frame_timestamp: datetime = Field(default_factory=utcnow)
    tracking_id: str = ""
    metadata: Dict = Field(default_factory=dict)

    def as_broadcast(self) -> dict:
        d = self.model_dump()
        d["type"] = "track_event"
        d["frame_timestamp"] = self.frame_timestamp.isoformat()
        return d


class TrackingMetricsOut(BaseModel):
    active_tracks: int = 0
    active_updates: int = 0
    lost_tracks: int = 0
    removed_tracks: int = 0
    total_updates: int = 0
    total_events: int = 0
    events_by_type: Dict[str, int] = Field(default_factory=dict)
    latency_avg_ms: float = 0.0
    latency_max_ms: float = 0.0
    started_at: datetime = Field(default_factory=utcnow)

    def as_broadcast(self) -> dict:
        d = self.model_dump()
        d["type"] = "tracking_metrics"
        d["latency_avg_ms"] = round(d["latency_avg_ms"], 3)
        d["latency_max_ms"] = round(d["latency_max_ms"], 3)
        d["started_at"] = self.started_at.isoformat()
        return d


class TrackSummary(BaseModel):
    tracking_id: str
    label: str
    state: TrackState
    bbox: List[int] = Field(default_factory=list)
    center: Optional[List[float]] = None
    confidence: float = 0.0
    hits: int = 1
    missing: int = 0


# back-compat alias used across the module graph
TrackingMetricsOut = TrackingMetricsOut
