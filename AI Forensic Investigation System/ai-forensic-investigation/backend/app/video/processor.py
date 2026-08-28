import json
import os
import logging
import traceback
from datetime import datetime

from app.database.session import SessionLocal
from app.database import models
from app.core.config import settings
from app.storage.service import storage
from app.video.pipeline import run_pipeline
from app.audit.service import record_audit

logger = logging.getLogger(__name__)

STAGES = [
    "UPLOAD",
    "METADATA",
    "SCENE_DETECTION",
    "CLIP_EXTRACTION",
    "DETECTION",
    "TRACKING",
    "INDEX_READY",
]


def _set_job(db, job_id: int, status: str, stage: str | None = None, progress: float | None = None, error: str | None = None):
    job = db.query(models.ProcessingJob).filter(models.ProcessingJob.id == job_id).first()
    if job:
        job.status = status
        if stage is not None:
            job.stage = stage
        if progress is not None:
            job.progress = progress
        if error is not None:
            job.error = error
        if status in ("PROCESSING", "QUEUED") and job.started_at is None:
            job.started_at = datetime.utcnow()
        if status in ("READY", "FAILED"):
            job.completed_at = datetime.utcnow()
        db.commit()


def process_video_job(video_id: int, job_id: int, local_video_path: str, user_id: int | None = None) -> None:
    """Background task: run the full pipeline and persist all results.

    This runs outside the request lifecycle, so it opens its own DB session.
    """
    db = SessionLocal()
    try:
        _set_job(db, job_id, "PROCESSING", "METADATA", 5.0)
        record_audit(db, "processing_start", user_id=user_id, entity_type="processing_job", entity_id=job_id, details=f"video_id={video_id}")

        result = run_pipeline(local_video_path, video_id, job_id, f"video_{video_id}")

        _persist_results(db, video_id, job_id, result, user_id)

        _set_job(db, job_id, "READY", "INDEX_READY", 100.0)
        video = db.query(models.Video).filter(models.Video.id == video_id).first()
        if video:
            video.status = "READY"
            db.commit()
        record_audit(db, "processing_complete", user_id=user_id, entity_type="processing_job", entity_id=job_id, details=f"video_id={video_id}")

    except Exception as exc:  # noqa: BLE001
        logger.error("Processing failed for video %s: %s", video_id, traceback.format_exc())
        _set_job(db, job_id, "FAILED", error=str(exc))
        video = db.query(models.Video).filter(models.Video.id == video_id).first()
        if video:
            video.status = "FAILED"
            db.commit()
        record_audit(db, "processing_failure", user_id=user_id, entity_type="processing_job", entity_id=job_id, details=f"video_id={video_id} error={exc}")
    finally:
        db.close()


def _persist_results(db, video_id: int, job_id: int, result: dict, user_id: int | None):
    db = db  # keep local session
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise ValueError(f"Video {video_id} not found")

    # Persist metadata onto the video row
    meta = result.get("metadata", {})
    video.duration_seconds = meta.get("duration")
    video.width = meta.get("width")
    video.height = meta.get("height")
    video.fps = meta.get("fps")
    video.codec = meta.get("codec")

    camera_id = video.camera_id

    for clip_data in result.get("clips", []):
        clip = models.Clip(
            public_id=clip_data["public_id"],
            video_id=video_id,
            camera_id=camera_id,
            start_time=clip_data["start_time"],
            end_time=clip_data["end_time"],
            storage_path=clip_data.get("storage_path"),
            thumbnail_path=clip_data.get("thumbnail_path"),
        )
        db.add(clip)
        db.flush()  # get clip.id

        for det in clip_data.get("detections", []):
            detection = models.Detection(
                clip_id=clip.id,
                video_id=video_id,
                camera_id=camera_id,
                label=det["label"],
                bounding_box=json.dumps(det["bbox"]),
                frame_number=det.get("frame_number"),
                timestamp=det.get("timestamp"),
                detection_confidence=det.get("confidence"),
                tracking_id=det.get("tracking_id"),
            )
            db.add(detection)
        db.flush()

    for event_data in result.get("events", []):
        clip_id = None
        if event_data.get("public_id"):
            clip = db.query(models.Clip).filter(models.Clip.public_id == event_data["public_id"]).first()
            clip_id = clip.id if clip else None
        event = models.Event(
            video_id=video_id,
            clip_id=clip_id,
            event_type=event_data["event_type"],
            description=event_data["description"],
            start_time=event_data.get("start_time"),
            end_time=event_data.get("end_time"),
            confidence=event_data.get("confidence"),
        )
        db.add(event)

    db.commit()
