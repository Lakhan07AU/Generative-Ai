"""Investigation agent tools (Part 3).

Each tool is a pure function that reads from the evidence store / RAG layers
and returns JSON-serialisable structures. Tools never mutate original evidence.

Evidence identity convention:
  * clip evidence id : "E-{clip_id:03d}"
  * frame evidence id: "E-F{frame_number}"
  * canonical clip ref : clip.public_id (e.g. CLIP-001)
Timestamps are always copied from source clips/frames - tools never invent them.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import models
from app.rag.video_rag import (
    analyze_query,
    retrieve_evidence,
    evidence_cards,
    video_rag_answer,
)
from app.rag.policy_rag import search_policies
from app.agents.guardrails import validate_timestamp


def clip_evidence_id(clip_id: int) -> str:
    return f"E-{int(clip_id):03d}"


def frame_evidence_id(frame_number: int) -> str:
    return f"E-F{int(frame_number)}"


# ---------------------------------------------------------------------------
# Low-level lookups
# ---------------------------------------------------------------------------

def _clip_summary(db: Session, clip_id: int) -> Optional[dict]:
    clip = db.query(models.Clip).filter(models.Clip.id == clip_id).first()
    if clip is None:
        return None
    objs = []
    trackings = set()
    max_conf = None
    for d in clip.detections:
        if d.label and d.label not in objs:
            objs.append(d.label)
        if d.tracking_id:
            trackings.add(d.tracking_id)
        if d.detection_confidence is not None and (
            max_conf is None or d.detection_confidence > max_conf
        ):
            max_conf = d.detection_confidence
    desc_model = clip.clip_description
    return {
        "clip_id": clip.id,
        "evidence_id": clip_evidence_id(clip.id),
        "clip_public_id": clip.public_id,
        "video_id": clip.video_id,
        "video_start": clip.video.start_time.timestamp() if clip.video and clip.video.start_time else None,
        "video_end": (clip.video.start_time.timestamp() + clip.video.duration_seconds)
        if clip.video and clip.video.start_time and clip.video.duration_seconds
        else (clip.video.duration_seconds if clip.video else None),
        "start_time": clip.start_time,
        "end_time": clip.end_time,
        "description": (desc_model.summary if desc_model else clip.description) or "",
        "objects": objs,
        "tracking_ids": sorted(trackings),
        "detection_confidence": round(max_conf, 3) if max_conf is not None else None,
    }


def get_clip_data(db: Session, clip_id: int) -> dict:
    summary = _clip_summary(db, clip_id)
    if summary is None:
        return {"found": False, "clip_id": clip_id, "reason": "clip not found"}
    clip = db.query(models.Clip).filter(models.Clip.id == clip_id).first()
    frames = []
    for d in clip.detections:
        if d.frame_number:
            frames.append(
                {
                    "frame_number": d.frame_number,
                    "timestamp": d.timestamp,
                    "label": d.label,
                    "evidence_id": frame_evidence_id(d.frame_number),
                    "tracking_id": d.tracking_id,
                    "confidence": d.detection_confidence,
                    "clip_id": clip.id,
                    "clip_public_id": clip.public_id,
                }
            )
    return {**summary, "found": True, "frames": frames[: settings.MAX_FRAMES_PER_CLIP]}


def get_frame_data(db: Session, video_id: int, frame_number: Optional[int] = None, timestamp: Optional[float] = None) -> dict:
    """Return frame-level evidence for a video. Frame numbers are authoritative
    (from detections); a source timestamp may also be validated."""
    q = db.query(models.Detection).filter(models.Detection.video_id == video_id)
    if frame_number is not None:
        q = q.filter(models.Detection.frame_number == frame_number)
    if timestamp is not None:
        lo = timestamp - settings.VERIFICATION_TIMESTAMP_TOLERANCE_SECONDS
        hi = timestamp + settings.VERIFICATION_TIMESTAMP_TOLERANCE_SECONDS
        q = q.filter(models.Detection.timestamp >= lo, models.Detection.timestamp <= hi)
    dets = q.limit(20).all()
    if not dets:
        return {"found": False, "video_id": video_id, "reason": "no frame/detection matched"}
    return {
        "found": True,
        "video_id": video_id,
        "frames": [
            {
                "frame_number": d.frame_number,
                "timestamp": d.timestamp,
                "label": d.label,
                "tracking_id": d.tracking_id,
                "confidence": d.detection_confidence,
                "evidence_id": frame_evidence_id(d.frame_number) if d.frame_number else None,
                "clip_id": d.clip_id,
                "clip_public_id": d.clip.public_id if d.clip else None,
            }
            for d in dets
            if d.frame_number is not None
        ],
    }


# ---------------------------------------------------------------------------
# Subject / entity searches
# ---------------------------------------------------------------------------

def search_person(db: Session, camera_id: Optional[int] = None, limit: int = 5) -> list[dict]:
    """Find clips whose detections include persons (humans), keyed by tracker."""
    return _search_by_label(db, {"person", "people"}, camera_id, limit)


def search_object(db: Session, label: str, camera_id: Optional[int] = None, limit: int = 5) -> list[dict]:
    """Find clips/detections containing a specific object label (car, van, bag...)."""
    return _search_by_label(db, {label}, camera_id, limit)


def _search_by_label(db: Session, labels: set[str], camera_id: Optional[int], limit: int) -> list[dict]:
    dets = (
        db.query(models.Detection)
        .filter(models.Detection.label.in_(sorted(labels)))
        .order_by(models.Detection.detection_confidence.desc())
        .limit(limit * 3)
        .all()
    )
    seen: dict[int, dict] = {}
    for d in dets:
        if camera_id and d.camera_id != camera_id:
            continue
        cid = d.clip_id
        if cid in seen:
            continue
        clip = get_clip_data(db, cid)
        if clip.get("found"):
            clip["subject"] = d.label
            clip["subject_tracking_id"] = d.tracking_id
            seen[cid] = clip
        if len(seen) >= limit:
            break
    return list(seen.values())


def search_event(db: Session, event_type: Optional[str] = None, video_id: Optional[int] = None,
                 start_time: Optional[float] = None, end_time: Optional[float] = None, limit: int = 20) -> list[dict]:
    """Search recorded events (typed detection/event rows) within optional bounds."""
    q = db.query(models.Event)
    if event_type:
        q = q.filter(models.Event.event_type.ilike(f"%{event_type}%"))
    if video_id:
        q = q.filter(models.Event.video_id == video_id)
    if start_time is not None:
        q = q.filter(models.Event.end_time >= start_time)
    if end_time is not None:
        q = q.filter(models.Event.start_time <= end_time)
    events = q.order_by(models.Event.start_time.asc()).limit(limit).all()
    return [
        {
            "id": ev.id,
            "event_type": ev.event_type,
            "description": ev.description,
            "start_time": ev.start_time,
            "end_time": ev.end_time,
            "confidence": ev.confidence,
            "video_id": ev.video_id,
            "clip_id": ev.clip_id,
            "clip_public_id": ev.clip.public_id if ev.clip else None,
            "evidence_id": clip_evidence_id(ev.clip_id) if ev.clip_id else None,
        }
        for ev in events
    ]


def search_video(db: Session, query: str, video_id: Optional[int] = None, camera_id: Optional[int] = None) -> dict:
    """Run the Part 2 video RAG pipeline and normalise results for the agent."""
    filters = {}
    if video_id:
        filters["video_id"] = video_id
    if camera_id:
        filters["camera_id"] = camera_id
    return video_rag_answer(db, query, filters or None)


def search_policy(db: Session, query: str, limit: int = 5) -> list[dict]:
    """Retrieve policy sections verbatim - never invented."""
    return search_policies(query, limit=limit)


# ---------------------------------------------------------------------------
# Timeline building
# ---------------------------------------------------------------------------

def build_timeline(db: Session, video_id: Optional[int] = None, start_time: Optional[float] = None,
                   end_time: Optional[float] = None, limit: Optional[int] = None) -> list[dict]:
    """Build an evidence-backed chronological timeline from events + detections."""
    events = search_event(db, event_type=None, video_id=video_id, start_time=start_time, end_time=end_time,
                          limit=settings.VERIFICATION_MAX_TIMELINE_EVENTS)
    entries: list[dict] = []
    for ev in events:
        if ev["start_time"] is None:
            continue
        entries.append({
            "timestamp": ev["start_time"],
            "kind": "event",
            "description": ev["description"] or ev["event_type"],
            "status": "VERIFIED" if (ev["confidence"] or 0) >= 0.5 else "UNVERIFIED",
            "evidence_ids": [ev["evidence_id"]] if ev["evidence_id"] else [],
            "clip_id": ev["clip_id"],
            "clip_public_id": ev["clip_public_id"],
        })

    # Add key detection moments as supplementary events.
    dets = db.query(models.Detection)
    if video_id:
        dets = dets.filter(models.Detection.video_id == video_id)
    if start_time is not None:
        dets = dets.filter(models.Detection.timestamp >= start_time)
    if end_time is not None:
        dets = dets.filter(models.Detection.timestamp <= end_time)
    for d in dets.order_by(models.Detection.timestamp.asc()).limit(50).all():
        if d.timestamp is None:
            continue
        entries.append({
            "timestamp": d.timestamp,
            "kind": "detection",
            "description": f"{d.label}" + (f" (tracker {d.tracking_id})" if d.tracking_id else ""),
            "status": "VERIFIED" if (d.detection_confidence or 0) >= 0.5 else "UNVERIFIED",
            "evidence_ids": [frame_evidence_id(d.frame_number) if d.frame_number else clip_evidence_id(d.clip_id)],
            "clip_id": d.clip_id,
            "clip_public_id": d.clip.public_id if d.clip else None,
        })

    entries.sort(key=lambda e: e["timestamp"])
    if limit:
        entries = entries[:limit]
    return entries


def summarize(result: Any) -> dict:
    """Produce a small, audit-safe summary of a tool result (no secrets)."""
    if isinstance(result, list):
        return {"count": len(result), "items": [summarize(r) for r in result[:5]]}
    if isinstance(result, dict):
        keys = list(result.keys())
        return {"keys": keys[:12], "count": len(result)}
    return {"type": type(result).__name__}
