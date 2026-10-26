import io
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database import models
from app.storage.service import storage
from app.auth.deps import get_current_user

router = APIRouter(prefix="/media", tags=["media"])

logger = logging.getLogger(__name__)


class MediaUrl(BaseModel):
    url: str


def _content_type_for(storage_path: str) -> str:
    lower = storage_path.lower()
    if lower.endswith(".mp4"):
        return "video/mp4"
    if lower.endswith(".webm"):
        return "video/webm"
    if lower.endswith(".ogg"):
        return "video/ogg"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".mp3"):
        return "audio/mpeg"
    if lower.endswith(".wav"):
        return "audio/wav"
    return "application/octet-stream"


def _proxy_url(request: Request, path: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}{path}"


def _serve_media_bytes(request: Request, data: bytes, content_type: str) -> Response:
    """Serve media bytes with HTTP Range request support for HTML5 video players."""
    total_size = len(data)
    range_header = request.headers.get("range")
    if range_header and range_header.startswith("bytes="):
        try:
            byte_range = range_header.replace("bytes=", "").strip()
            parts = byte_range.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else total_size - 1

            if start >= total_size or end >= total_size or start > end:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{total_size}"},
                )

            chunk_len = end - start + 1
            chunk = data[start : end + 1]
            return Response(
                content=chunk,
                status_code=206,
                media_type=content_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(chunk_len),
                },
            )
        except (ValueError, IndexError):
            pass

    return Response(
        content=data,
        status_code=200,
        media_type=content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(total_size),
        },
    )


@router.get("/clips/{clip_id}", response_model=MediaUrl)
def clip_media_url(
    request: Request,
    clip_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    clip = db.query(models.Clip).filter(models.Clip.id == clip_id).first()
    if not clip or not clip.storage_path:
        raise HTTPException(status_code=404, detail="Clip not found or no storage path")
    return MediaUrl(url=_proxy_url(request, f"/media/clips/{clip_id}/file"))


@router.get("/clips/{clip_id}/file")
def clip_media_file(
    request: Request,
    clip_id: int,
    db: Session = Depends(get_db),
):
    clip = db.query(models.Clip).filter(models.Clip.id == clip_id).first()
    if not clip or not clip.storage_path:
        raise HTTPException(status_code=404, detail="Clip not found")
    try:
        data = storage.get_bytes(clip.storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Clip file not found on storage")
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to read clip %s: %s", clip_id, exc)
        raise HTTPException(status_code=500, detail="could not read clip")
    return _serve_media_bytes(request, data, _content_type_for(clip.storage_path))


@router.get("/thumbnails/{clip_id}", response_model=MediaUrl)
def thumbnail_media_url(
    request: Request,
    clip_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    clip = db.query(models.Clip).filter(models.Clip.id == clip_id).first()
    if not clip or not clip.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return MediaUrl(url=_proxy_url(request, f"/media/thumbnails/{clip_id}/file"))


@router.get("/thumbnails/{clip_id}/file")
def thumbnail_media_file(
    request: Request,
    clip_id: int,
    db: Session = Depends(get_db),
):
    clip = db.query(models.Clip).filter(models.Clip.id == clip_id).first()
    if not clip or not clip.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    try:
        data = storage.get_bytes(clip.thumbnail_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Thumbnail file not found on storage")
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to read thumbnail %s: %s", clip_id, exc)
        raise HTTPException(status_code=500, detail="could not read thumbnail")
    return _serve_media_bytes(request, data, _content_type_for(clip.thumbnail_path))


@router.get("/original/{video_id}", response_model=MediaUrl)
def original_media_url(
    request: Request,
    video_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video or not video.storage_path:
        raise HTTPException(status_code=404, detail="Video not found or no storage path")
    return MediaUrl(url=_proxy_url(request, f"/media/original/{video_id}/file"))


@router.get("/original/{video_id}/file")
def original_media_file(
    request: Request,
    video_id: int,
    db: Session = Depends(get_db),
):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video or not video.storage_path:
        raise HTTPException(status_code=404, detail="Video not found")
    try:
        data = storage.get_bytes(video.storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Video file not found on storage")
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to read video %s: %s", video_id, exc)
        raise HTTPException(status_code=500, detail="could not read video")
    return _serve_media_bytes(request, data, _content_type_for(video.storage_path))
