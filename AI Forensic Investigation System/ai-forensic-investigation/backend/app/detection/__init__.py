"""Phase 2 real-time YOLO detection layer."""

from app.detection.engine import (
    DetectionEngine,
    DetectionError,
    InvalidFrameError,
    InvalidModelError,
    ModelNotFoundError,
    clear_engines,
    get_engine,
)
from app.detection.metrics import DetectionMetrics
from app.detection.pipeline import DetectionPipeline, detection_enabled
from app.detection.schemas import BoundingBox, DetectionFrame, DetectionObject
from app.detection.worker import DetectionWorker

__all__ = [
    "BoundingBox",
    "DetectionEngine",
    "DetectionError",
    "DetectionFrame",
    "DetectionMetrics",
    "DetectionObject",
    "DetectionPipeline",
    "DetectionWorker",
    "InvalidFrameError",
    "InvalidModelError",
    "ModelNotFoundError",
    "clear_engines",
    "detection_enabled",
    "get_engine",
]