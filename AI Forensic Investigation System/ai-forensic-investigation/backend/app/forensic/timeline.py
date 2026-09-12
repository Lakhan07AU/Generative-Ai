"""Phase 8 forensic timeline reconstruction.

Reconstructs an evidence-backed chronological timeline from the evidence used
by a Phase 7 run. Entries are merged only when the same tracked object / event
type / observation fall within a small epsilon window; genuinely different
times always produce separate entries. Intermediate events are never invented.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from app.forensic import semantics, timestamps
from app.evidence.schemas import parse_metadata


def _entry_source(evidence_types: Set[str]) -> str:
    if "TRACK_EVENT" in evidence_types:
        return "tracking"
    if "VLM_OBSERVATION" in evidence_types:
        return "vlm"
    if "FRAME" in evidence_types or "DETECTION" in evidence_types:
        return "frame"
    return "correlated"


def _describe(rows, camera_names: Dict[int, str]) -> str:
    tracks = [r for r in rows if getattr(r, "evidence_type", None) == "TRACK_EVENT"]
    vlms = [r for r in rows if getattr(r, "evidence_type", None) == "VLM_OBSERVATION"]
    frames = [r for r in rows if getattr(r, "evidence_type", None) in ("FRAME", "DETECTION")]
    clock = ""
    if tracks:
        evt = tracks[0]
        camera_name = camera_names.get(getattr(evt, "camera_id", None))
        clock = timestamps.format_hhmmss(timestamps.event_time_of(evt))
        return semantics.describe_event(
            getattr(evt, "event_type", None),
            getattr(evt, "object_class", None),
            getattr(evt, "tracking_id", None),
            camera_name,
            clock,
        )
    if vlms:
        obs = vlms[0]
        camera_name = camera_names.get(getattr(obs, "camera_id", None))
        clock = timestamps.format_hhmmss(timestamps.event_time_of(obs))
        observed = []
        items = parse_metadata(obs)
        item_list = items.get("items") or items.get("statements") or []
        if not isinstance(item_list, list):
            item_list = []
        for item in item_list[:3]:
            text = ""
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("statement") or "")
            elif isinstance(item, str):
                text = item
            if semantics.revert_observed_guard(text):
                observed.append(text.lstrip("[OBSERVED] ").strip())
        if observed:
            snippet = " ".join(f'"{t}"' for t in observed)
            return f"VLM observation {getattr(obs, 'vlm_observation_id', 'n/a')} at camera {camera_name} at {clock} ({snippet})."
        return f"VLM observation {getattr(obs, 'vlm_observation_id', 'n/a')} was logged at camera {camera_name} at {clock}; it contains no literal observed statement."
    if frames:
        fr = frames[0]
        camera_name = camera_names.get(getattr(fr, "camera_id", None))
        clock = timestamps.format_hhmmss(timestamps.event_time_of(fr))
        resolution = timestamps.resolution_of(fr)
        dims = f" ({resolution['width']}x{resolution['height']})" if resolution else ""
        return f"A source frame{dims} was captured at camera {camera_name} at {clock}."
    return "A correlated forensic entry with no visual source was recorded."


def build_forensic_timeline(
    rows,
    camera_names: Dict[int, str],
    *,
    conflicting_ids: Optional[Set[str]] = None,
    max_entries: int = 200,
    epsilon: float = 2.0,
    analytics_time: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    conflicting_ids = conflicting_ids or set()
    normalized = []
    for row in rows:
        evt_time = timestamps.event_time_of(row)
        normalized.append((evt_time, row))
    normalized.sort(key=lambda pair: (pair[0] if pair[0] is not None else -1, getattr(pair[1], "id", 0) or 0))

    clusters: List[List[Any]] = []
    for event_time, row in normalized:
        if event_time is None:
            continue
        if not clusters:
            clusters.append([row])
            continue
        last = clusters[-1]
        if _same_cluster(last[-1], row, event_time, epsilon):
            last.append(row)
        else:
            clusters.append([row])

    entries: List[Dict[str, Any]] = []
    for index, cluster in enumerate(clusters[: int(max_entries)]):
        cluster.sort(key=lambda r: getattr(r, "id", 0) or 0)
        event_times = [timestamps.event_time_of(r) for r in cluster]
        event_time = min(t for t in event_times if t is not None) if any(event_times) else event_times[0]
        end_ts = max(t for t in event_times if t is not None) if any(event_times) else None
        if end_ts is not None and end_ts <= (event_time or 0) + 1e-9:
            end_ts = None

        evidence_types = {getattr(r, "evidence_type", "") or "" for r in cluster}
        evidence_ids = [getattr(r, "public_id", None) for r in cluster]
        evidence_ids = [eid for eid in evidence_ids if eid]

        candidates = [eid for eid in evidence_ids if eid in conflicting_ids]
        is_conflicted = bool(candidates)

        camera_ids = {getattr(r, "camera_id", None) for r in cluster}
        camera_id = next((c for c in camera_ids if c is not None), None)
        camera_name = camera_names.get(camera_id) if camera_id else None
        session_ids = {getattr(r, "session_id", None) for r in cluster}
        session_id = next((s for s in session_ids if s is not None), None)
        track_ids = {getattr(r, "tracking_id", None) for r in cluster}
        track_id = next((t for t in track_ids if t), None)
        event_ids = {getattr(r, "event_id", None) for r in cluster}
        event_id = next((e for e in event_ids if e), None)
        event_types = {getattr(r, "event_type", None) for r in cluster}
        event_type = next((e for e in event_types if e), None)
        classes = {getattr(r, "object_class", None) for r in cluster}
        object_class = next((c for c in classes if c), None) or getattr(cluster[0], "object_class", None)

        vlm_ids = {getattr(r, "vlm_observation_id", None) for r in cluster}
        vlm_id = next((v for v in vlm_ids if v), None)

        quality = []
        for r in cluster:
            for flag in semantics.quality_flags_of(r, 480):
                if flag not in quality:
                    quality.append(flag)

        event_times_float = [t for t in event_times if t is not None]
        has_track = "TRACK_EVENT" in evidence_types
        has_observed_vlm = any(
            semantics.revert_observed_guard(text)
            for r in cluster
            if getattr(r, "evidence_type", None) == "VLM_OBSERVATION"
            for text in _vlm_texts(r)
        )
        has_unobserved_vlm = any(
            getattr(r, "evidence_type", None) == "VLM_OBSERVATION" and not any(semantics.revert_observed_guard(t) for t in _vlm_texts(r))
            for r in cluster
        )

        if is_conflicted:
            classification = semantics.CONFLICTING
            verification_status = semantics.CONTRADICTED
        elif has_track or has_observed_vlm or ("FRAME" in evidence_types and event_times_float):
            classification = semantics.OBSERVED
            verification_status = semantics.VERIFIED
        elif evidence_ids and event_times_float:
            if has_unobserved_vlm:
                classification = semantics.INFERRED
                verification_status = semantics.UNVERIFIED_STATUS
            else:
                classification = semantics.INFERRED
                verification_status = semantics.PARTIALLY_VERIFIED
        else:
            classification = semantics.UNVERIFIED
            verification_status = semantics.UNVERIFIED_STATUS

        if "LOW_RESOLUTION" in quality and classification == semantics.OBSERVED and not has_track:
            classification = semantics.INFERRED
            verification_status = semantics.PARTIALLY_VERIFIED

        confidence = {
            semantics.OBSERVED: 0.9,
            semantics.INFERRED: 0.6,
            semantics.UNVERIFIED: 0.4,
            semantics.UNKNOWN: 0.2,
            semantics.CONFLICTING: 0.1,
        }.get(classification, 0.4)

        source = _entry_source(evidence_types)
        storage = next((timestamps.storage_time_of(r) for r in cluster if timestamps.storage_time_of(r)), None)
        analysis = next((timestamps.analysis_time_of(r) for r in cluster if timestamps.analysis_time_of(r)), None)

        note = semantics.WITHIN_VIEW_NOTE
        if "LOW_RESOLUTION" in quality:
            note = "The available evidence is low resolution; details may be unreliable."
        if object_class and has_track:
            note = f"{note} {semantics.IDENTITY_NOTE}"

        entries.append(
            {
                "timeline_event_id": f"TL-{index + 1:02d}",
                "timestamp": event_time if event_time is not None else 0,
                "end_timestamp": end_ts,
                "camera_id": camera_id,
                "camera_name": camera_name,
                "session_id": session_id,
                "event_id": event_id,
                "track_id": track_id,
                "object_class": object_class,
                "event_type": event_type,
                "vlm_observation_id": vlm_id,
                "evidence_ids": evidence_ids,
                "event_type_set": sorted(evidence_types),
                "description": _describe(cluster, camera_names),
                "classification": classification,
                "confidence": round(confidence, 2),
                "source": source,
                "verification_status": verification_status,
                "quality_flags": quality,
                "notes": note,
                "event_time": event_time,
                "analysis_time": timestamps.iso_utc(analysis),
                "storage_time": timestamps.iso_utc(storage),
                "analytics_time": timestamps.iso_utc(analytics_time),
                "conflicts": sorted(candidates),
            }
        )
    return entries


def _vlm_texts(row) -> List[str]:
    out = []
    items = parse_metadata(row)
    item_list = items.get("items") or items.get("statements") or []
    if not isinstance(item_list, list):
        return []
    for item in item_list:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("statement") or item.get("summary") or "")
        elif isinstance(item, str):
            text = item
        else:
            continue
        if text:
            out.append(text)
    summary = str(items.get("summary") or "")
    if summary:
        out.append(summary)
    return out


def _same_cluster(last_row, row, new_time: float, epsilon: float) -> bool:
    last_time = timestamps.event_time_of(last_row)
    if last_time is None:
        return False
    if abs(new_time - last_time) > epsilon:
        return False
    if getattr(last_row, "camera_id", None) != getattr(row, "camera_id", None):
        return False
    last_session = getattr(last_row, "session_id", None)
    new_session = getattr(row, "session_id", None)
    if last_session is not None and new_session is not None and last_session != new_session:
        return False
    last_vlm = getattr(last_row, "vlm_observation_id", None)
    new_vlm = getattr(row, "vlm_observation_id", None)
    if last_vlm or new_vlm:
        return last_vlm is not None and last_vlm == new_vlm
    last_track = getattr(last_row, "tracking_id", None)
    new_track = getattr(row, "tracking_id", None)
    if not last_track or not new_track:
        return False
    if last_track != new_track:
        return False
    last_type = getattr(last_row, "event_type", None)
    new_type = getattr(row, "event_type", None)
    if last_type and new_type and last_type != new_type:
        return False
    return True