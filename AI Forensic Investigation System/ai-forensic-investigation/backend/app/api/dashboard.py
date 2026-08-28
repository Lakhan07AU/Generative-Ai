from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database.session import get_db
from app.database import models
from app.schemas.video import DashboardStats, VideoOut
from app.auth.deps import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    total_videos = db.query(models.Video).count()
    processing_jobs = db.query(models.ProcessingJob).filter(
        models.ProcessingJob.status.in_(["QUEUED", "PROCESSING"])
    ).count()
    completed_videos = db.query(models.Video).filter(models.Video.status == "READY").count()
    total_detections = db.query(models.Detection).count()

    recent = db.query(models.Video).order_by(models.Video.uploaded_at.desc()).limit(5).all()
    recent_out = []
    for v in recent:
        vo = VideoOut.model_validate(v)
        if v.camera:
            vo.camera_name = v.camera.camera_name
        recent_out.append(vo)

    return DashboardStats(
        total_videos=total_videos,
        processing_jobs=processing_jobs,
        completed_videos=completed_videos,
        total_detections=total_detections,
        recent_videos=recent_out,
    )
