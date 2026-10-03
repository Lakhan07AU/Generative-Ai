"""Index a processed video into the Phase 5/6 forensic evidence store.

For uploaded/stored videos the offline enrichment writes clip descriptions and
transcripts only (Phase 2). The Phase 6/7 investigation retrieval reads
``ForensicEvidence`` rows plus Qdrant points carrying ``evidence_id`` /
``object_class`` / ``tracking_id`` / ``timestamp`` (produced by the live-capture
path). This script bridges that gap for stored videos so controlled
investigations can retrieve video-derived evidence.

It derives, for each clip:

  * one ``TRACK_EVENT`` evidence row per distinct (label, tracking_id), and
  * one ``VLM_OBSERVATION`` row per clip that has a stored description.

Rows + vector points are reseeded deterministically (old ``EVD-VID..`` rows are
wiped first) so re-runs are idempotent.

Run from ``backend/``::

    python -m scripts.index_video_evidence --video 2
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from app.ai.embeddings import embeddings
from app.ai.qdrant_service import qdrant
from app.core.config import settings
from app.database import models
from app.database.session import SessionLocal
from app.evidence.schemas import (
    IndexStatus,
    build_provenance,
    evidence_index_payload,
    observation_content,
    serialize_metadata,
    serialize_provenance,
    track_event_content,
)

_PREFIX = "EVD-VID"


def _wipe_video_evidence(db, video_id: int) -> int:
    prefix = f"{_PREFIX}{video_id}-"
    rows = db.query(models.ForensicEvidence).filter(models.ForensicEvidence.public_id.like(f"{prefix}%")).all()
    for row in rows:
        try:
            qdrant.delete(settings.QDRANT_COLLECTION_EVIDENCE, row.public_id)
        except Exception:  # noqa: BLE001
            pass
        db.delete(row)
    return len(rows)


class _EventLike:
    def __init__(self, event_type: str, tracking_id: Optional[str], frame_index: Optional[int], label: Optional[str]):
        self.event_type = event_type
        self.tracking_id = tracking_id
        self.frame_index = frame_index
        self.metadata = {"label": label} if label else {}


def _insert_and_index(
    db,
    *,
    evidence_type: str,
    public_id: str,
    camera_id: Optional[int],
    frame_timestamp: Optional[float],
    window_start: Optional[float],
    window_end: Optional[float],
    event_type: Optional[str],
    tracking_id: Optional[str],
    object_class: Optional[str],
    content_text: str,
    metadata: Dict,
) -> models.ForensicEvidence:
    caption = f"video evidence {public_id} camera_id={camera_id}"
    provenance = build_provenance(
        public_id=public_id,
        evidence_type=evidence_type,
        source="DERIVED",
        camera_id=camera_id,
        session_id=None,
        event_id=None,
        event_type=event_type,
        tracking_id=tracking_id,
        frame_sequence=None,
        frame_timestamp=frame_timestamp,
        vlm_observation_id=None,
        source_frame_ids=[],
        window_start=window_start,
        window_end=window_end,
        captured_at=datetime.utcnow().isoformat(),
        storage_path=None,
        mime_type=None,
        width=None,
        height=None,
        sha256=None,
        size_bytes=None,
    )
    metadata["video_id"] = metadata.get("video_id")
    row = models.ForensicEvidence(
        public_id=public_id,
        evidence_type=evidence_type,
        source="DERIVED",
        camera_id=camera_id,
        session_id=None,
        event_id=None,
        event_type=event_type,
        tracking_id=tracking_id,
        frame_sequence=None,
        frame_timestamp=frame_timestamp,
        window_start=window_start,
        window_end=window_end,
        vlm_observation_id=None,
        source_frame_ids="[]",
        captured_at=datetime.utcnow(),
        storage_path=None,
        mime_type=None,
        width=None,
        height=None,
        sha256=None,
        size_bytes=None,
        content_text=content_text,
        extra_metadata=serialize_metadata(metadata),
        provenance=serialize_provenance(provenance),
        index_status=IndexStatus.INDEXED.value,
        indexed_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    vec = embeddings.embed_text(content_text or caption)
    payload = evidence_index_payload(
        evidence_id=public_id,
        evidence_type=evidence_type,
        source="DERIVED",
        camera_id=camera_id,
        session_id=None,
        timestamp=frame_timestamp,
        event_id=None,
        event_type=event_type,
        tracking_id=tracking_id,
        frame_sequence=None,
        vlm_observation_id=None,
        storage_path=None,
        sha256=None,
        source_text=content_text,
        object_class=object_class,
    )
    qdrant.ensure_collections()
    qdrant.index_evidence(public_id, vec, payload)
    return row


def index_video_evidence(video_id: int, db=None) -> Dict:
    """Reseed forensic evidence derived from a processed video."""
    own = db is None
    db = db or SessionLocal()
    try:
        video = db.query(models.Video).filter(models.Video.id == video_id).first()
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        clips = db.query(models.Clip).filter(models.Clip.video_id == video_id).order_by(models.Clip.id).all()
        if not clips:
            raise ValueError(f"Video {video_id} has no clips")

        camera_name = video.camera.camera_name if video.camera else ""
        wiped = _wipe_video_evidence(db, video_id)

        track_count = 0
        obs_count = 0
        for clip in clips:
            dets = db.query(models.Detection).filter(models.Detection.clip_id == clip.id).all()
            groups: Dict[tuple, List[models.Detection]] = {}
            for d in dets:
                key = (d.label, d.tracking_id)
                groups.setdefault(key, []).append(d)
            label_hist: Dict[str, int] = {}
            for (label, tracking_id), dd in groups.items():
                label_hist[label] = label_hist.get(label, 0) + len(dd)
                ts = next((d.timestamp for d in dd if d.timestamp is not None), clip.start_time)
                content = track_event_content(
                    _EventLike("object_detected", tracking_id, None, label),
                    camera_name,
                )
                _insert_and_index(
                    db,
                    evidence_type="TRACK_EVENT",
                    public_id=f"{_PREFIX}{video_id}-{clip.id}-{track_count}",
                    camera_id=video.camera_id,
                    frame_timestamp=ts,
                    window_start=clip.start_time,
                    window_end=clip.end_time,
                    event_type="object_detected",
                    tracking_id=tracking_id,
                    object_class=label,
                    content_text=content,
                    metadata={"label": label, "video_id": video_id, "clip_id": clip.id},
                )
                track_count += 1

            desc = db.query(models.ClipDescription).filter(models.ClipDescription.clip_id == clip.id).first()
            if desc and (desc.summary or desc.objects):
                objects = json.loads(desc.objects or "[]")
                actions = json.loads(desc.observable_actions or "[]")
                items = []
                if desc.summary:
                    items.append({"statement": desc.summary, "classification": "OBSERVED", "confidence": 0.9})
                for o in objects:
                    items.append({"statement": f"{o} observed in clip", "classification": "OBSERVED", "confidence": 0.9})
                for a in actions:
                    items.append({"statement": f"{a} observed in clip", "classification": "OBSERVED", "confidence": 0.8})
                content = observation_content(
                    {
                        "summary": desc.summary or "Stored clip observation",
                        "items": items,
                        "trigger": "clip",
                        "trigger_detail": " ".join(
                            f"{k} x{n}" for k, n in sorted(label_hist.items(), key=lambda kv: -kv[1])
                        ),
                    }
                )
                _insert_and_index(
                    db,
                    evidence_type="VLM_OBSERVATION",
                    public_id=f"{_PREFIX}{video_id}-OBS-{clip.id}",
                    camera_id=video.camera_id,
                    frame_timestamp=clip.start_time,
                    window_start=clip.start_time,
                    window_end=clip.end_time,
                    event_type=None,
                    tracking_id=None,
                    object_class=None,
                    content_text=content,
                    metadata={"video_id": video_id, "clip_id": clip.id, "objects": objects},
                )
                obs_count += 1

        db.commit()
        return {
            "video_id": video_id,
            "camera_id": video.camera_id,
            "clips": len(clips),
            "track_events": track_count,
            "observations": obs_count,
            "wiped": wiped,
        }
    finally:
        if own:
            db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Index a processed video into forensic evidence")
    parser.add_argument("--video", type=int, required=True, help="video id to index")
    parser.add_argument("--generate-uuid", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    manifest = index_video_evidence(args.video)
    print("Indexed video evidence:")
    for key, value in manifest.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()