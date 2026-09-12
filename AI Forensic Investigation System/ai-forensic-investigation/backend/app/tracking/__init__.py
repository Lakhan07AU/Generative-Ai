"""Phase 3 real-time multi-object tracking layer.

One tracker/detector/metrics per (session, camera) - never shared across
cameras. Only VISUAL tracking identifiers (no facial recognition, names, or
biometric identification). Motion/bbox units are ABSOLUTE frame pixels.
"""

from app.tracking.event_detector import EventThresholds, TrackEventDetector
from app.tracking.metrics import TrackingMetrics
from app.tracking.motion import (
    CENTER_MAX_PX,
    center_of_bbox,
    displacement_px,
    moving_seconds,
    path_distance_px,
    pixel_velocity_px_per_frame,
    stationary_ratio,
    stationary_seconds,
)
from app.tracking.pipeline import TrackingPipeline
from app.tracking.schemas import (
    TrackState,
    TrackingEvent,
    TrackingMetricsOut,
    TrackSummary,
    TrackUpdate,
    utcnow,
)
from app.tracking.tracker import IoUMultiObjectTracker

__all__ = [
    "CENTER_MAX_PX", "EventThresholds", "IoUMultiObjectTracker",
    "TrackEventDetector", "TrackingMetrics", "TrackingMetricsOut",
    "TrackingPipeline", "TrackingEvent", "TrackState", "TrackSummary",
    "TrackUpdate", "center_of_bbox", "displacement_px", "moving_seconds",
    "path_distance_px", "pixel_velocity_px_per_frame", "stationary_ratio",
    "stationary_seconds", "utcnow",
]
