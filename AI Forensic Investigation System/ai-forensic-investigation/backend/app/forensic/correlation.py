"""Phase 8 evidence correlation: provenance chains and cross-evidence links.

Correlation is read-only: it builds derived structures over existing evidence
and never modifies the underlying evidence rows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.forensic import timestamps
from app.evidence.schemas import parse_metadata, parse_provenance, parse_source_frame_ids

EVENT_FRAME_EPSILON = 2.0


def evidence_chain(row, camera_name: Optional[str]) -> Dict[str, Any]:
    """The visible lineage for one evidence record (finding -> evidence)."""
    evidence_type = getattr(row, "evidence_type", "") or ""
    meta = parse_metadata(row)
    prov = parse_provenance(row)
    nodes: List[Dict[str, Any]] = []
    if evidence_type == "TRACK_EVENT" and (getattr(row, "tracking_id", None) or getattr(row, "event_id", None)):
        nodes.append(
            {
                "role": "event",
                "label": getattr(row, "event_type", None) or "track event",
                "event_id": getattr(row, "event_id", None) or meta.get("event_id"),
                "tracking_id": getattr(row, "tracking_id", None) or meta.get("tracking_id"),
            }
        )
        nodes.append({"role": "track", "tracking_id": getattr(row, "tracking_id", None) or meta.get("tracking_id")})
    if evidence_type == "DETECTION" or evidence_type == "TRACK_EVENT":
        frame_seq = meta.get("frame_index") or meta.get("frame_sequence")
        nodes.append({"role": "detection", "frame": frame_seq, "label": meta.get("label")})
    source_frames = parse_source_frame_ids(row)
    if evidence_type == "VLM_OBSERVATION" or source_frames:
        nodes.append({"role": "frame", "source_frame_ids": source_frames})
    nodes.append({"role": "evidence", "evidence_id": getattr(row, "public_id", None), "evidence_type": evidence_type})
    return {
        "evidence_id": getattr(row, "public_id", None),
        "evidence_type": evidence_type,
        "camera_id": getattr(row, "camera_id", None),
        "camera_name": camera_name,
        "session_id": getattr(row, "session_id", None),
        "timestamp": timestamps.event_time_of(row),
        "nodes": nodes,
    }


def _rows_by_public_id(rows) -> Dict[str, Any]:
    return {getattr(r, "public_id", None): r for r in rows}


def correlate_evidence(rows, camera_names: Dict[int, str]) -> List[Dict[str, Any]]:
    """Build read-only correlations between the evidence used by a run."""
    by_public = _rows_by_public_id(rows)
    correlations: List[Dict[str, Any]] = []

    by_tracking: Dict[str, List[Any]] = {}
    by_vlm: Dict[str, List[Any]] = {}
    frames_by_id: Dict[int, str] = {}
    frame_keys: Dict[tuple, List[Any]] = {}

    for row in rows:
        track = getattr(row, "tracking_id", None)
        if track:
            by_tracking.setdefault(track, []).append(row)
        vlm_id = getattr(row, "vlm_observation_id", None)
        if vlm_id:
            by_vlm.setdefault(vlm_id, []).append(row)
        if getattr(row, "evidence_type", None) == "FRAME":
            fid = getattr(row, "id", None)
            if fid:
                frames_by_id[fid] = getattr(row, "public_id", None)
            key = (getattr(row, "camera_id", None), getattr(row, "session_id", None))
            frame_keys.setdefault(key, []).append(row)

    for track, group in by_tracking.items():
        if len(group) > 1:
            correlations.append(
                {
                    "kind": "track_sequence",
                    "tracking_id": track,
                    "evidence": [getattr(r, "public_id", None) for r in sorted(group, key=lambda r: timestamps.event_time_of(r) or 0)],
                    "relationship": "SAME_TRACK",
                    "note": "Multiple evidence records reference the same tracked object. They are treated as the same tracked object, not independent identities.",
                }
            )

    for vlm_id, group in by_vlm.items():
        vlm_rows = [r for r in group if getattr(r, "evidence_type", None) == "VLM_OBSERVATION"]
        if not vlm_rows:
            continue
        obs = vlm_rows[0]
        window_start = timestamps.event_time_of(obs)
        related = []
        for candidate in group:
            if candidate is obs:
                continue
            related.append(getattr(candidate, "public_id", None))
        if related:
            correlations.append(
                {
                    "kind": "vlm_observation_chain",
                    "vlm_observation_id": vlm_id,
                    "evidence": [getattr(obs, "public_id", None)],
                    "related": related,
                    "relationship": "SOURCE_FRAMES",
                    "note": f"VLM observation {vlm_id} is grounded in its recorded source frames.",
                }
            )

    for key, frame_group in frame_keys.items():
        events = [r for r in rows if (getattr(r, "camera_id", None), getattr(r, "session_id", None)) == key and getattr(r, "evidence_type", None) == "TRACK_EVENT"]
        for evt in events:
            evt_time = timestamps.event_time_of(evt)
            if evt_time is None:
                continue
            for fr in frame_group:
                fr_time = timestamps.event_time_of(fr)
                if fr_time is None:
                    continue
                if abs(evt_time - fr_time) <= EVENT_FRAME_EPSILON:
                    correlations.append(
                        {
                            "kind": "event_source_frame",
                            "evidence": [getattr(evt, "public_id", None)],
                            "related": [getattr(fr, "public_id", None)],
                            "relationship": "SOURCE_FRAME",
                            "note": "A tracking event coincides with a captured source frame at the same absolute time.",
                        }
                    )
                    break

    for row in rows:
        source_ids = parse_source_frame_ids(row)
        if not source_ids:
            continue
        related = [frames_by_id.get(fid) for fid in source_ids]
        related = [rid for rid in related if rid]
        if related:
            correlations.append(
                {
                    "kind": "detection_source_frames",
                    "evidence": [getattr(row, "public_id", None)],
                    "related": related,
                    "relationship": "SOURCE_FRAME",
                    "note": "An evidence record declares its origin as specific captured source frames.",
                }
            )
    return correlations


def source_authorities(rows, camera_names: Dict[int, str]) -> List[Dict[str, Any]]:
    """Authority note per evidence: server-side labels outrank derived text."""
    out: List[Dict[str, Any]] = []
    for row in rows:
        evidence_type = getattr(row, "evidence_type", "") or ""
        authority = "server_event"
        note = "Populated by the tracking/pipeline from server capture data."
        if evidence_type == "VLM_OBSERVATION":
            authority = "vlm_derived"
            note = "Derived VLM text; only [OBSERVED] statements are treated as literal observations."
        out.append(
            {
                "evidence_id": getattr(row, "public_id", None),
                "authority": authority,
                "source": "metadata" if evidence_type != "VLM_OBSERVATION" else "vlm",
                "note": note,
            }
        )
    return out