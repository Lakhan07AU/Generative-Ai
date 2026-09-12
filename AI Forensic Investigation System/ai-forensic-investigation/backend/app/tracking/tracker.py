"""IoU multi-object tracker with persistent visual IDs (Phase 3).

MATCH: greedy IoU over ABSOLUTE px bboxes, same label, strongest-conf first;
LOST tracks preferred for recovery. Bounded: max_tracks, max_missing, bounded
center/bbox/timestamp histories. Thread-safe. Visual IDs only.
"""

import math
import threading
from datetime import datetime
from typing import Dict, List, Optional

from app.tracking.motion import center_of_bbox, displacement_px, path_distance_px, pixel_velocity_px_per_frame
from app.tracking.schemas import TrackState, TrackUpdate, TrackSummary, utcnow


class _InternalTrack:
    __slots__ = (
        "id", "label", "state", "bbox", "confidence", "hits", "missing",
        "centers", "bbox_history", "created_at", "last_seen_at",
    )

    def __init__(self, tid, label, bbox, confidence):
        self.id = tid
        self.label = label
        self.state = TrackState.NEW
        self.bbox = list(bbox)
        self.confidence = float(confidence)
        self.hits = 1
        self.missing = 0
        c = center_of_bbox(bbox)
        self.centers = [c]
        self.bbox_history = [list(bbox)]
        self.created_at = utcnow()
        self.last_seen_at = self.created_at


def _iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    ub = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = ua + ub - inter
    return inter / union if union > 0 else 0.0


class IoUMultiObjectTracker:
    def __init__(self, iou_threshold=0.3, max_missing=30, max_tracks=200):
        self.iou_threshold = float(iou_threshold)
        self.max_missing = int(max_missing)
        self.max_tracks = int(max_tracks)
        self._tracks: Dict[str, _InternalTrack] = {}
        self._lock = threading.RLock()
        self._seq = 0

    def _new_id(self):
        self._seq += 1
        return f"Person-{self._seq:06d}"

    def update(self, detections, frame_index, ts=None):
        ts = ts or utcnow()
        results = []
        with self._lock:
            ordered = sorted(detections, key=lambda d: d.get("confidence", 0.0), reverse=True)
            used = set()
            for det in ordered:
                if len(self._tracks) >= self.max_tracks:
                    break
                bbox = list(det.get("bbox") or [0, 0, 0, 0])
                label = det.get("label", "Person")
                best_tid, best_iou = None, self.iou_threshold
                for tid, tr in self._tracks.items():
                    if tid in used or tr.label != label:
                        continue
                    score = _iou(tr.bbox, bbox)
                    tie = 1e-6 if tr.state == TrackState.LOST else 0.0
                    if score + tie > best_iou:
                        best_iou, best_tid = score, tid
                if best_tid is not None:
                    tr = self._tracks[best_tid]
                    used.add(best_tid)
                    prev_center = tr.centers[-1]
                    prev_bbox = tr.bbox_history[-1] if tr.bbox_history else None
                    tr.bbox = bbox
                    tr.confidence = det.get("confidence", tr.confidence)
                    tr.hits += 1
                    tr.missing = 0
                    tr.last_seen_at = ts
                    nc = center_of_bbox(bbox)
                    tr.centers.append(nc)
                    tr.bbox_history.append(list(bbox))
                    if tr.state == TrackState.NEW and tr.hits >= 3:
                        tr.state = TrackState.ACTIVE
                    elif tr.state == TrackState.LOST:
                        tr.state = TrackState.ACTIVE
                    if len(tr.centers) > 60:
                        tr.centers = tr.centers[-60:]
                        tr.bbox_history = tr.bbox_history[-60:]
                    results.append(self._from_track(tr, frame_index, ts, prev_center, prev_bbox))
                else:
                    tr = _InternalTrack(self._new_id(), label, bbox, det.get("confidence", 0.0))
                    self._tracks[tr.id] = tr
                    results.append(self._from_track(tr, frame_index, ts, None, None))

            for tid, tr in list(self._tracks.items()):
                if tid not in used:
                    tr.missing += 1
                    if tr.missing > self.max_missing:
                        tr.state = TrackState.REMOVED
                        self._tracks.pop(tid, None)
                    elif tr.state in (TrackState.NEW, TrackState.ACTIVE):
                        tr.state = TrackState.LOST
        return results

    def _from_track(self, tr, frame_index, ts, prev_center, prev_bbox):
        c = center_of_bbox(tr.bbox)
        disp = displacement_px(prev_center, c) if prev_center else 0.0
        direction = None
        if prev_center:
            dx, dy = c[0] - prev_center[0], c[1] - prev_center[1]
            if dx or dy:
                direction = round((math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0, 3)
        return TrackUpdate(
            session_id="", camera_id="", frame_index=frame_index,
            frame_timestamp=ts, tracking_id=tr.id, state=tr.state,
            label=tr.label, confidence=round(tr.confidence, 4), bbox=tr.bbox,
            center=c, displacement_px=round(disp, 3), direction_deg=direction,
            pixel_velocity=pixel_velocity_px_per_frame(tr.centers),
            distance_traveled_px=path_distance_px(tr.centers),
            stationary_seconds=0.0, moving_seconds=0.0, stationary_ratio=0.0,
            width_px=round(tr.bbox[2] - tr.bbox[0], 2),
            height_px=round(tr.bbox[3] - tr.bbox[1], 2),
            width_delta_px=0.0, height_delta_px=0.0,
            hits=tr.hits, missing=tr.missing,
        )

    def tracks(self):
        with self._lock:
            return [
                TrackSummary(tracking_id=tr.id, label=tr.label, state=tr.state,
                             bbox=tr.bbox, center=tr.centers[-1],
                             confidence=round(tr.confidence, 4),
                             hits=tr.hits, missing=tr.missing)
                for tr in self._tracks.values()
            ]

    def remove_all(self):
        with self._lock:
            self._tracks.clear()

    def reset(self):
        self.remove_all()
