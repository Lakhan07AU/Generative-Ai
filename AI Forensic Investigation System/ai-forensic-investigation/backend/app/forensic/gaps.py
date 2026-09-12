"""Phase 8 evidence-gap and evidence-quality detection.

Gaps are reported where the available evidence cannot support a claim; nothing
is ever asserted about activity outside the observed camera coverage.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.forensic import semantics, timestamps
from app.evidence.schemas import parse_source_frame_ids


def detect_evidence_gaps(
    rows,
    *,
    query: str,
    covered_camera_names: List[str],
    gap_threshold_seconds: float = 30.0,
    low_resolution_px: int = 480,
) -> Dict[str, Any]:
    gaps: List[Dict[str, Any]] = []

    event_times = sorted(
        t for t in (timestamps.event_time_of(r) for r in rows) if t is not None
    )
    if len(event_times) >= 2:
        missing: List[Dict[str, Any]] = []
        for i in range(len(event_times) - 1):
            delta = event_times[i + 1] - event_times[i]
            if delta > gap_threshold_seconds:
                missing.append(
                    {
                        "start": event_times[i],
                        "end": event_times[i + 1],
                        "duration_seconds": round(delta, 2),
                        "reason": "No captured evidence was available during this range.",
                    }
                )
        if missing:
            gaps.append(
                {
                    "kind": "missing_time_ranges",
                    "detail": missing,
                    "note": "The evidence covers specific instants; ranges without captured evidence are unobservable.",
                }
            )

    gaps.append(
        {
            "kind": "missing_camera_coverage",
            "detail": {"cameras": covered_camera_names},
            "note": "Evidence is limited to the cameras shown to the investigation. Activity outside their field of view is not observable.",
        }
    )

    rows_by_public = {getattr(r, "public_id", None): r for r in rows}
    missing_frames: List[str] = []
    for row in rows:
        if getattr(row, "evidence_type", None) != "VLM_OBSERVATION":
            continue
        declared = parse_source_frame_ids(row)
        for fid in declared:
            owners = [
                getattr(c, "public_id", None)
                for c in rows
                if any(int(x) == fid for x in parse_source_frame_ids(c)) or getattr(c, "id", None) == fid
            ]
            if not owners:
                missing_frames.append(f"declared frame {fid} for observation {getattr(row, 'vlm_observation_id', 'n/a')}")
    if missing_frames:
        gaps.append(
            {
                "kind": "missing_frames",
                "detail": {"frames": missing_frames},
                "note": "An observation declares source frames that are not present in the evidence used by this run.",
            }
        )

    low_res = [
        getattr(r, "public_id", None)
        for r in rows
        if semantics.quality_flags_of(r, low_resolution_px) and "LOW_RESOLUTION" in semantics.quality_flags_of(r, low_resolution_px)
    ]
    if low_res:
        gaps.append(
            {
                "kind": "insufficient_resolution",
                "detail": {"evidence": low_res},
                "note": "Low-resolution frames may not support fine-grained detail claims.",
            }
        )

    occluded = [
        getattr(r, "public_id", None)
        for r in rows
        if "OCCLUDED" in semantics.quality_flags_of(r, low_resolution_px)
    ]
    if occluded:
        gaps.append(
            {
                "kind": "occlusion",
                "detail": {"evidence": occluded},
                "note": "Obscured views may hide objects or actions from the camera.",
            }
        )

    unknown_objects = [
        getattr(r, "public_id", None)
        for r in rows
        if not getattr(r, "object_class", None)
    ]
    if unknown_objects:
        gaps.append(
            {
                "kind": "unknown_objects",
                "detail": {"evidence": unknown_objects},
                "note": "Some evidence records do not identify an object class.",
            }
        )

    quality_map: Dict[str, List[str]] = {}
    for row in rows:
        flags = semantics.quality_flags_of(row, low_resolution_px)
        if flags:
            quality_map[getattr(row, "public_id", None)] = flags

    return {
        "gaps": gaps,
        "quality": quality_map,
        "coverage": {"cameras": covered_camera_names, "note": "All correlations are limited to the covered cameras."},
    }