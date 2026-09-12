"""Phase 8 multi-camera correlation.

Correlations across cameras are reported as POSSIBLE_CORRELATION or UNKNOWN.
Never assert that two observations are the same object across cameras without
corroborating evidence.
"""

from __future__ import annotations

from typing import Any, Dict, List


def correlate_across_cameras(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_track: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        track = entry.get("track_id")
        if not track:
            continue
        by_track.setdefault(track, []).append(entry)

    results: List[Dict[str, Any]] = []
    for track, group in by_track.items():
        cameras: Dict[str, Dict[str, Any]] = {}
        for entry in group:
            cam_id = entry.get("camera_id")
            cam_name = entry.get("camera_name")
            key = cam_name if cam_name else (str(cam_id) if cam_id is not None else "unknown")
            prev = cameras.setdefault(
                key,
                {"camera_id": cam_id, "camera_name": cam_name, "count": 0, "start": entry.get("timestamp"), "end": entry.get("timestamp")},
            )
            prev["count"] += 1
            t = entry.get("timestamp")
            if t is not None:
                if prev.get("start") is None or t < prev["start"]:
                    prev["start"] = t
                if prev.get("end") is None or t > prev["end"]:
                    prev["end"] = t
        if len(cameras) <= 1:
            continue
        camera_list = list(cameras.values())
        status = "POSSIBLE_CORRELATION"
        reason = (
            f"Track {track} was observed on cameras {', '.join(c['camera_name'] or str(c['camera_id']) for c in camera_list)}. "
            "Corroborating evidence (matching appearance or overlapping times) is required before treating these as the same object."
        )
        results.append(
            {
                "track_id": track,
                "cameras": camera_list,
                "status": status,
                "note": reason,
            }
        )
    return results