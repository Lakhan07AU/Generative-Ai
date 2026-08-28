"""Video semantic understanding (Part 2).

Converts each processed clip into structured evidence:

1. Re-extract a small set of keyframes from the clip.
2. Send keyframes -> VLM -> structured semantic description
   (summary, objects, observable_actions, location_context, transcript_reference).
3. Embed the description (and transcript) and index into Qdrant ``video_evidence``.
4. Run Whisper over the clip audio -> timestamped transcript, embed + index.
5. Persist ``ClipDescription`` / ``Transcript`` rows.

Only observable evidence is described. The VLM is instructed not to infer human
intent, identities, or names. In simulation mode the description is built from
the actual stored detections for the clip (or is honestly empty).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime

from app.core.config import settings
from app.database import models
from app.database.session import SessionLocal
from app.ai import provider, whisper
from app.ai.embeddings import embeddings
from app.ai.qdrant_service import qdrant
from app.video.ffmpeg_utils import extract_frame
from app.storage.service import storage

logger = logging.getLogger(__name__)

MAX_VISION_FRAMES = 3


# ---------------------------------------------------------------------------
# Keyframe extraction
# ---------------------------------------------------------------------------

def _extract_keyframes(video_path: str, clip_start: float, clip_end: float, out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    duration = max(0.1, (clip_end - clip_start) or 0.5)
    n = min(MAX_VISION_FRAMES, max(1, int(duration) // 2 or 1))
    paths = []
    step = duration / (n + 1)
    for i in range(1, n + 1):
        t = clip_start + step * i
        out = os.path.join(out_dir, f"kf_{i}.jpg")
        try:
            extract_frame(video_path, t, out)
            if os.path.exists(out) and os.path.getsize(out) > 0:
                paths.append(out)
        except Exception as exc:  # noqa: BLE001
            logger.warning("keyframe extraction failed at %s: %s", t, exc)
    return paths


# ---------------------------------------------------------------------------
# Clip -> description + payload
# ---------------------------------------------------------------------------

def build_clip_payload(video, clip, description, transcript_text: str) -> dict:
    """Build Qdrant payload metadata for an evidence point."""
    objects = []
    tracking = []
    if description:
        try:
            objects = json.loads(description.objects) if description.objects else []
        except (json.JSONDecodeError, TypeError):
            objects = []
    dets = clip.detections or []
    tracking = sorted({d.tracking_id for d in dets if d.tracking_id})

    return {
        "video_id": video.id,
        "camera_id": video.camera_id,
        "clip_id": clip.id,
        "start_time": float(clip.start_time),
        "end_time": float(clip.end_time),
        "event_type": _clip_event_types(clip),
        "objects": objects,
        "tracking_ids": tracking,
        "transcript": transcript_text,
        "description": (description.summary if description else ""),
    }


def _clip_event_types(clip) -> list[str]:
    types = set()
    for ev in (clip.events or []):
        if ev.event_type:
            types.add(ev.event_type)
    return sorted(types)


# ---------------------------------------------------------------------------
# Full video enrichment entrypoint
# ---------------------------------------------------------------------------

def enrich_video(video_id: int, user_id: int | None = None) -> dict:
    """Run semantic enrichment for a video: VLM descriptions + whisper transcripts,
    embed and index into Qdrant, and persist DB records."""
    from app.database.session import SessionLocal as _SL

    db = _SL()
    try:
        video = db.query(models.Video).filter(models.Video.id == video_id).first()
        if not video:
            raise ValueError(f"Video {video_id} not found")

        clips = db.query(models.Clip).filter(models.Clip.video_id == video_id).order_by(models.Clip.id).all()
        if not clips:
            raise ValueError(f"Video {video_id} has no clips to enrich")

        # Fetch original video locally for keyframe/audio extraction.
        local = _fetch_original(video)
        work = os.path.join(settings.DATA_DIR, "work", f"enrich_video_{video_id}")
        os.makedirs(work, exist_ok=True)

        qdrant.ensure_collections()
        indexed = 0
        transcripts = 0
        for idx, clip in enumerate(clips, start=1):
            frame_dir = os.path.join(work, f"clip_{clip.id}")
            keyframes = _extract_keyframes(local, clip.start_time, clip.end_time, frame_dir)

            dets = [d for d in (clip.detections or [])]
            clip_context = {
                "start_time": clip.start_time,
                "end_time": clip.end_time,
                "detections": [
                    {
                        "label": d.label,
                        "tracking_id": d.tracking_id,
                        "confidence": d.detection_confidence,
                    }
                    for d in dets
                ],
                "location_context": f"clip {clip.public_id} camera {video.camera_id}",
                "transcript_reference": f"video {video_id} clip {clip.id}",
            }

            description = provider.vision_describe_clip(keyframes, clip_context)

            # persist description
            desc = models.ClipDescription(
                clip_id=clip.id,
                video_id=video_id,
                summary=description.get("summary", ""),
                objects=json.dumps(description.get("objects", [])),
                observable_actions=json.dumps(description.get("observable_actions", [])),
                location_context=description.get("location_context", ""),
                transcript_reference=description.get("transcript_reference", ""),
                source="vlm" if provider.available() else "simulation",
                confidence=0.9 if provider.available() else 0.5,
            )
            db.add(desc)
            db.flush()

            # transcript for the clip
            segs = whisper.transcribe(local, clip.start_time, clip.end_time)
            tr_text = " ".join(s["text"] for s in segs)
            for s in segs:
                db.add(
                    models.Transcript(
                        video_id=video_id,
                        clip_id=clip.id,
                        start_time=s["start_time"],
                        end_time=s["end_time"],
                        text=s["text"],
                        confidence=s.get("confidence"),
                    )
                )
            transcripts += len(segs)

            # embed description text + transcript reference
            embed_input = (
                f"{description.get('summary', '')} objects: {', '.join(description.get('objects', []) or [])} "
                f"actions: {', '.join(description.get('observable_actions', []) or [])}"
            )
            vec = embeddings.embed_text(embed_input)
            payload = build_clip_payload(video, clip, desc, tr_text)
            qdrant.index_evidence(clip.id, vec, payload)
            indexed += 1

            db.commit()

        # mark video as semantic-ready
        video.status = "READY"  # keep READY but we could add semantic flag; keep READY
        db.commit()
        record_enrichment(db, video_id, user_id, indexed, transcripts)

        return {"video_id": video_id, "clips_indexed": indexed, "transcript_segments": transcripts}
    finally:
        db.close()


def record_enrichment(db, video_id: int, user_id: int | None, indexed: int, transcripts: int):
    try:
        from app.audit.service import record_audit

        record_audit(
            db,
            "semantic_enrich",
            user_id=user_id,
            entity_type="video",
            entity_id=video_id,
            details=f"clips_indexed={indexed} transcript_segments={transcripts}",
        )
    except Exception:  # noqa: BLE001
        pass


def _fetch_original(video) -> str:
    """Download the immutable original from MinIO to a local temp file."""
    work = os.path.join(settings.DATA_DIR, "work", f"vid_{video.id}")
    os.makedirs(work, exist_ok=True)
    _, ext = os.path.splitext(video.filename)
    target = os.path.join(work, f"original{ext or '.mp4'}")
    data = storage.get_bytes(video.storage_path)
    with open(target, "wb") as f:
        f.write(data)
    return target


# ---------------------------------------------------------------------------
# Convenience for querying stored semantic data for a video
# ---------------------------------------------------------------------------

def get_video_evidence_rows(db, video_id: int):
    return (db.query(models.ClipDescription).filter(models.ClipDescription.video_id == video_id).all())
