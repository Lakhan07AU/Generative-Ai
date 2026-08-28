import os
import tempfile
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database import models
from app.schemas.video import (
    VideoOut,
    VideoDetail,
    ProcessingJobOut,
    ClipOut,
    DetectionOut,
    EventOut,
    DashboardStats,
)
from app.auth.deps import get_current_user, require_roles
from app.audit.service import record_audit
from app.storage.service import storage
from app.core.config import settings

router = APIRouter(prefix="/videos", tags=["videos"])

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}


def _validate_extension(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )
    return ext


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    camera_id: Optional[int] = Form(None),
    camera_name: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    recording_date: Optional[str] = Form(None),
    start_time: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    ext = _validate_extension(file.filename or "")

    # Resolve camera (either existing by id or create by name)
    camera = None
    if camera_id:
        camera = db.query(models.Camera).filter(models.Camera.id == camera_id).first()
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")
    elif camera_name:
        camera = models.Camera(camera_name=camera_name, location=location)
        db.add(camera)
        db.flush()

    camera_id_value = camera.id if camera else None

    # Parse optional date strings
    rec_date = _parse_datetime(recording_date)
    start_dt = _parse_datetime(start_time)

    # Save upload locally first (required for ffmpeg processing)
    data_dir = settings.DATA_DIR
    videos_local_dir = os.path.join(data_dir, "videos")
    os.makedirs(videos_local_dir, exist_ok=True)
    local_path = os.path.join(videos_local_dir, f"upload_{current_user.id}_{datetime.utcnow().timestamp():.0f}{ext}")
    with open(local_path, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)

    file_size = os.path.getsize(local_path)
    if file_size == 0:
        os.remove(local_path)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Upload to MinIO as immutable original evidence
    storage.ensure_buckets()
    storage_path = storage.put_file(
        "videos",
        local_path,
        storage.unique_name(f"video_{current_user.id}", ext),
        content_type=f"video/{ext.lstrip('.')}",
        lock=True,  # original evidence stays immutable
    )

    video = models.Video(
        filename=file.filename or os.path.basename(local_path),
        storage_path=storage_path,
        camera_id=camera_id_value,
        recording_date=rec_date,
        start_time=start_dt,
        description=description,
        status="UPLOADED",
        uploaded_by_user_id=current_user.id,
    )
    db.add(video)
    db.flush()

    job = models.ProcessingJob(video_id=video.id, status="QUEUED", stage="UPLOAD", progress=0.0)
    db.add(job)
    db.commit()
    db.refresh(video)
    db.refresh(job)

    record_audit(
        db,
        "video_upload",
        user_id=current_user.id,
        entity_type="video",
        entity_id=video.id,
        details=f"filename={video.filename} size={file_size}",
    )

    # Kick off background processing (do not block the request)
    background_tasks.add_task(process_video_job_runner, video.id, job.id, local_path, current_user.id)

    return {"video_id": video.id, "processing_job_id": job.id, "status": video.status, "filename": video.filename}


def process_video_job_runner(video_id: int, job_id: int, local_path: str, user_id: int):
    """Wrapper so the route does not import the heavy processor module eagerly."""
    from app.video.processor import process_video_job

    process_video_job(video_id, job_id, local_path, user_id)


@router.get("", response_model=list[VideoOut])
def list_videos(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    videos = db.query(models.Video).order_by(models.Video.uploaded_at.desc()).all()
    result = []
    for v in videos:
        vo = VideoOut.model_validate(v)
        if v.camera:
            vo.camera_name = v.camera.camera_name
        result.append(vo)
    return result


@router.get("/{video_id}", response_model=VideoDetail)
def get_video(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    vd = VideoDetail.model_validate(video)
    if video.camera:
        vd.camera_name = video.camera.camera_name
    return vd


@router.get("/{video_id}/status", response_model=ProcessingJobOut)
def get_video_status(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    job = (
        db.query(models.ProcessingJob)
        .filter(models.ProcessingJob.video_id == video_id)
        .order_by(models.ProcessingJob.id.desc())
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="No processing job found for video")
    return job


@router.post("/{video_id}/process", response_model=ProcessingJobOut)
def process_video(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Recreate a job
    job = models.ProcessingJob(video_id=video_id, status="QUEUED", stage="UPLOAD", progress=0.0)
    db.add(job)
    db.commit()
    db.refresh(job)
    video.status = "QUEUED"
    db.commit()

    # Recover the original local file from MinIO storage
    data_dir = settings.DATA_DIR
    local_dir = os.path.join(data_dir, "videos")
    os.makedirs(local_dir, exist_ok=True)
    _, ext = os.path.splitext(video.filename)
    local_path = os.path.join(local_dir, f"reprocess_{video_id}_{datetime.utcnow().timestamp():.0f}{ext or '.mp4'}")
    data = storage.get_bytes(video.storage_path)
    with open(local_path, "wb") as f:
        f.write(data)

    record_audit(db, "processing_reprocess", user_id=current_user.id, entity_type="video", entity_id=video_id)
    background_tasks.add_task(process_video_job_runner, video.id, job.id, local_path, current_user.id)
    return job


@router.post("/{video_id}/enrich", status_code=status.HTTP_202_ACCEPTED)
def enrich_video(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Trigger Part 2 multimodal enrichment (transcription + clip description + vector index)."""
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if video.status not in ("COMPLETED",):
        raise HTTPException(status_code=409, detail="Video must be COMPLETED before enrichment")

    jobs = db.query(models.ProcessingJob).filter(
        models.ProcessingJob.video_id == video_id,
        models.ProcessingJob.status.in_(["QUEUED", "RUNNING"]),
    ).count()
    if jobs:
        raise HTTPException(status_code=409, detail="A processing job is already running for this video")

    record_audit(db, "processing_enrich", user_id=current_user.id, entity_type="video", entity_id=video_id)

    def _run():
        from app.ai.video_understanding import enrich_video

        try:
            enrich_video(video_id, user_id=current_user.id)
        except Exception:  # noqa: BLE001
            db.rollback()

    background_tasks.add_task(_run)
    return {"detail": "Enrichment queued", "video_id": video_id}


# ----- detail sub-resources -----

@router.get("/{video_id}/clips", response_model=list[ClipOut])
def list_clips(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return db.query(models.Clip).filter(models.Clip.video_id == video_id).order_by(models.Clip.start_time).all()


@router.get("/{video_id}/detections", response_model=list[DetectionOut])
def list_detections(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Detection)
        .filter(models.Detection.video_id == video_id)
        .order_by(models.Detection.timestamp)
        .all()
    )


@router.get("/{video_id}/events", response_model=list[EventOut])
def list_events(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return db.query(models.Event).filter(models.Event.video_id == video_id).order_by(models.Event.start_time).all()


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
