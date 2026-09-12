"""Builds the observable metadata context for a VLM observation (Phase 4).

The context bundles ONLY facts already known to the system: camera/session
ids, source frame refs, the detection frame closest to the trigger, active
tracks (with ABSOLUTE PIXEL boxes - never stored/serialised identities), and
the triggering event. This is the "YOLO + tracking + VLM fusion" input.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _latest_detections(runtime) -> List[dict]:
    """Compact view of the most recent detection frame (if any)."""
    if runtime is None or runtime.detection is None:
        return []
    try:
        recent = runtime.detection.recent_results(limit=5)
    except Exception:  # noqa: BLE001
        return []
    # Prefer the newest frame that actually contains detections.
    for frame in reversed(recent):
        dets = frame.get("detections") or []
        if not dets:
            continue
        return [
            {
                "label": d.get("class_name") or d.get("label") or "object",
                "confidence": float(d.get("confidence", 0.0) or 0.0),
                "bbox": _as_px_list(d.get("bbox")),
                "frame_id": frame.get("frame_id"),
            }
            for d in dets
        ]
    return []


def _as_px_list(bbox) -> Optional[List[int]]:
    if bbox is None:
        return None
    if hasattr(bbox, "x1"):
        return [int(bbox.x1), int(bbox.y1), int(bbox.x2), int(bbox.y2)]
    try:
        item = list(bbox)
        return [int(v) for v in item[:4]]
    except (TypeError, ValueError):
        return None


def _active_tracks(runtime) -> List[dict]:
    """Compact view of currently active tracked objects (visual ids only)."""
    if runtime is None or runtime.tracking is None:
        return []
    try:
        tracks = runtime.tracking.tracks()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for t in tracks:
        # TrackSummary fields: tracking_id, label, state, bbox, center,
        # confidence, hits, missing.
        state = getattr(t, "state", None)
        state = getattr(state, "value", state)
        if state in ("NEW", "ACTIVE"):
            out.append(
                {
                    "tracking_id": str(getattr(t, "tracking_id", "")),
                    "label": str(getattr(t, "label", "") or "object"),
                    "state": str(state),
                    "bbox": _as_px_list(getattr(t, "bbox", None)),
                    "center": list(getattr(t, "center", []) or []),
                    "confidence": float(getattr(t, "confidence", 0.0) or 0.0),
                }
            )
    return out


def build_observe_context(
    runtime,
    *,
    camera_id: int,
    camera_name: Optional[str],
    session_id: Optional[int],
    trigger: str,
    trigger_detail: Optional[str],
    source_frames: List[dict],
    window_start: Optional[float],
    window_end: Optional[float],
    event: Optional[dict] = None,
    provider_mode: str = "simulation",
) -> Dict[str, Any]:
    """Compose the observable context handed to the VLM (and simulation fallback)."""
    detections = _latest_detections(runtime)
    tracks = _active_tracks(runtime)
    frame_refs = [
        {
            "frame_id": f.get("frame_id"),
            "sequence": f.get("sequence"),
            "timestamp": f.get("timestamp"),
            "width": f.get("width", 0),
            "height": f.get("height", 0),
        }
        for f in source_frames
    ]
    return {
        "camera_id": camera_id,
        "camera_name": camera_name or "",
        "session_id": session_id,
        "trigger": trigger,
        "trigger_detail": trigger_detail,
        "provider_mode": provider_mode,
        "source_frames": frame_refs,
        "window_start": window_start,
        "window_end": window_end,
        "detections": detections,
        "active_tracks": tracks,
        "event": event,
        "coordinate_units": "absolute_frame_pixels",
        "no_faces": True,
    }