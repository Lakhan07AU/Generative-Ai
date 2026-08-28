from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database import models
from app.storage.service import storage
from app.auth.deps import get_current_user

router = APIRouter(prefix="/media", tags=["media"])


class MediaUrl(BaseModel):
    url: str


@router.get("/clips/{clip_id}", response_model=MediaUrl)
def clip_media_url(
    clip_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    clip = db.query(models.Clip).filter(models.Clip.id == clip_id).first()
    if not clip or not clip.storage_path:
        raise HTTPException(status_code=404, detail="Clip not found or no storage path")
    return MediaUrl(url=storage.presigned_url(clip.storage_path))


@router.get("/thumbnails/{clip_id}", response_model=MediaUrl)
def thumbnail_media_url(
    clip_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    clip = db.query(models.Clip).filter(models.Clip.id == clip_id).first()
    if not clip or not clip.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return MediaUrl(url=storage.presigned_url(clip.thumbnail_path))


@router.get("/original/{video_id}", response_model=MediaUrl)
def original_media_url(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video or not video.storage_path:
        raise HTTPException(status_code=404, detail="Video not found or no storage path")
    return MediaUrl(url=storage.presigned_url(video.storage_path))
