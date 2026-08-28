"""Lightweight multi-object tracker.

Implements a simple, dependency-light IoU-based (ByteTrack-style) tracker that
assigns persistent visual tracking IDs (e.g. Person-001) across consecutive
frames. This is a visual tracking identifier only - it does NOT perform facial
recognition, name identification, or biometric identification.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Track:
    id: str
    label: str
    bbox: list  # [x1, y1, x2, y2]
    last_frame: int
    hits: int = 1
    missing: int = 0
    max_missing: int = 30


def iou(a: list, b: list) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


class IoUTracker:
    def __init__(self, iou_threshold: float = 0.3, max_missing: int = 30):
        self.iou_threshold = iou_threshold
        self.max_missing = max_missing
        self.tracks: dict[str, Track] = {}
        self._counter = 0

    def _new_id(self, label: str) -> str:
        self._counter += 1
        return f"{label}-{self._counter:03d}"

    def predict(self, frame_index: int):
        """Advance timestamps for active tracks."""
        for t in self.tracks.values():
            t.missing += 1

    def update(self, detections: list[dict], frame_index: int) -> list[dict]:
        """Match detections to existing tracks, then create new ones.

        detections: list of dicts with label, bbox, confidence.
        Returns detection dicts annotated with a persistent tracking_id.
        """
        self.predict(frame_index)

        # Sort detections by confidence (high-to-low) so the strongest matches first
        ordered = sorted(
            detections, key=lambda d: d.get("confidence", 0.0), reverse=True
        )

        used_dets = set()
        # Match each detection to best existing track of the same label
        for i, det in enumerate(ordered):
            best_track_id = None
            best_iou = self.iou_threshold
            for tid, tr in self.tracks.items():
                if tr.label != det["label"]:
                    continue
                if tr.missing > self.max_missing:
                    continue
                score = iou(tr.bbox, det["bbox"])
                if score > best_iou:
                    best_iou = score
                    best_track_id = tid
            if best_track_id is not None:
                tr = self.tracks[best_track_id]
                tr.bbox = det["bbox"]
                tr.last_frame = frame_index
                tr.missing = 0
                tr.hits += 1
                det["tracking_id"] = best_track_id
                used_dets.add(i)

        # Create new tracks for unmatched detections
        for i, det in enumerate(ordered):
            if i in used_dets:
                continue
            tid = self._new_id(det["label"])
            self.tracks[tid] = Track(
                id=tid,
                label=det["label"],
                bbox=det["bbox"],
                last_frame=frame_index,
                max_missing=self.max_missing,
            )
            det["tracking_id"] = tid

        # Drop stale tracks
        stale = [tid for tid, tr in self.tracks.items() if tr.missing > self.max_missing]
        for tid in stale:
            del self.tracks[tid]

        return detections


class DetectionModel:
    """YOLO detection wrapper with a robust fallback.

    Loads Ultralytics YOLO when available. If the model file is missing or the
    `ultralytics` package is not installed, yields NO detections rather than
    fabricating results.
    """

    def __init__(self, model_path: str):
        self.model = None
        try:
            from ultralytics import YOLO

            self.model = YOLO(model_path)
        except Exception:
            self.model = None

    def available(self) -> bool:
        return self.model is not None

    def detect(self, frame):
        """Return list of detection dicts: label, bbox [x1,y1,x2,y2], confidence, class."""
        if self.model is None:
            return []
        results = self.model.predict(frame, verbose=False)
        detections = []
        if not results:
            return detections
        boxes = results[0].boxes
        if boxes is None:
            return detections
        names = results[0].names
        for box in boxes:
            xyxy = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            cls = int(box.cls[0])
            label = names.get(cls, "object")
            detections.append(
                {
                    "label": label,
                    "bbox": [round(v, 2) for v in xyxy],
                    "confidence": round(conf, 4),
                    "class": cls,
                }
            )
        return detections
