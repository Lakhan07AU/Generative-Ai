"""Phase 2 detection schemas.

These stable Pydantic models are the contract between the live pipeline
(``app/live``), the YOLO inference layer (``app/detection``), and future
consumers (Phase 3 tracking, Phase 4 event detection, Phase 5 VLM, Phase 6
evidence storage). Do not change bounding-box format here without a migration
strategy, since every downstream phase reads this schema.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Absolute pixel coordinates in the frame image space.

    Convention: ``x1, y1`` is the top-left corner, ``x2, y2`` is the
    bottom-right corner (both inclusive). Coordinates are NOT normalized.
    """

    x1: int = Field(ge=0)
    y1: int = Field(ge=0)
    x2: int = Field(ge=0)
    y2: int = Field(ge=0)

    def is_valid(self, width: Optional[int] = None, height: Optional[int] = None) -> bool:
        if self.x2 < self.x1 or self.y2 < self.y1:
            return False
        if width is not None and (self.x1 > width or self.x2 > width):
            return False
        if height is not None and (self.y1 > height or self.y2 > height):
            return False
        return True


class DetectionObject(BaseModel):
    """A single detected object within one frame."""

    detection_id: str
    class_id: int = Field(ge=0)
    class_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BoundingBox
    frame_timestamp: float
    session_id: Optional[int] = None
    frame_id: Optional[int] = None
    camera_id: Optional[int] = None
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None


class DetectionFrame(BaseModel):
    """All detections for one sampled frame (the unit broadcast to clients)."""

    session_id: Optional[int] = None
    camera_id: Optional[int] = None
    frame_id: Optional[int] = None
    frame_timestamp: float
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    detections: List[DetectionObject] = Field(default_factory=list)

    def as_broadcast(self) -> dict:
        """Compact JSON payload sent over the detection WebSocket."""
        return {
            "type": "detection",
            "session_id": self.session_id,
            "camera_id": self.camera_id,
            "frame_id": self.frame_id,
            "timestamp": self.frame_timestamp,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "detections": [
                {
                    "class_id": d.class_id,
                    "class_name": d.class_name,
                    "confidence": d.confidence,
                    "bbox": [d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2],
                }
                for d in self.detections
            ],
        }