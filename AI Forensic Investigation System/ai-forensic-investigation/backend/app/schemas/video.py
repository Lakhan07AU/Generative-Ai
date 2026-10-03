from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class CameraCreate(BaseModel):
    camera_name: str
    location: Optional[str] = None
    description: Optional[str] = None
    camera_type: Optional[str] = "CCTV"  # CCTV | MOBILE | OTHER
    stream_source: Optional[str] = None
    # CCTV automation defaults (migration 0009)
    auto_process: Optional[bool] = False
    onvif_host: Optional[str] = None
    onvif_username: Optional[str] = None
    rtsp_url: Optional[str] = None
    rtsp_url_alt: Optional[str] = None
    max_processing_fps: Optional[float] = None


class CameraUpdate(BaseModel):
    camera_name: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    camera_type: Optional[str] = None
    stream_source: Optional[str] = None
    auto_process: Optional[bool] = None
    onvif_host: Optional[str] = None
    onvif_username: Optional[str] = None
    rtsp_url: Optional[str] = None
    rtsp_url_alt: Optional[str] = None
    max_processing_fps: Optional[float] = None


class CameraOut(BaseModel):
    id: int
    camera_name: str
    location: Optional[str] = None
    description: Optional[str] = None
    camera_type: Optional[str] = "CCTV"
    stream_source: Optional[str] = None
    is_live: bool = False
    stream_status: str = "OFFLINE"
    # CCTV automation (migration 0009). onvif_username is shadowed so the
    # credential reference never leaks; raw secrets are never serialized.
    auto_process: Optional[bool] = False
    onvif_host: Optional[str] = None
    onvif_username: Optional[str] = None
    rtsp_url: Optional[str] = None
    rtsp_url_alt: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    health_status: str = "OFFLINE"
    last_error: Optional[str] = None
    reconnect_attempts: int = 0
    max_processing_fps: Optional[float] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ProcessingJobOut(BaseModel):
    id: int
    video_id: int
    status: str
    stage: Optional[str] = None
    progress: float
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class VideoOut(BaseModel):
    id: int
    filename: str
    storage_path: str
    camera_id: Optional[int] = None
    duration_seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    codec: Optional[str] = None
    recording_date: Optional[datetime] = None
    start_time: Optional[datetime] = None
    description: Optional[str] = None
    status: str
    uploaded_at: Optional[datetime] = None
    camera_name: Optional[str] = None

    model_config = {"from_attributes": True}


class ClipOut(BaseModel):
    id: int
    public_id: str
    video_id: int
    camera_id: Optional[int] = None
    start_time: float
    end_time: float
    storage_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class DetectionOut(BaseModel):
    id: int
    clip_id: int
    video_id: int
    camera_id: Optional[int] = None
    label: str
    bounding_box: str
    frame_number: Optional[int] = None
    timestamp: Optional[float] = None
    detection_confidence: Optional[float] = None
    tracking_id: Optional[str] = None

    model_config = {"from_attributes": True}


class EventOut(BaseModel):
    id: int
    video_id: int
    clip_id: Optional[int] = None
    event_type: str
    description: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    confidence: Optional[float] = None

    model_config = {"from_attributes": True}


class ClipDetail(ClipOut):
    detections: List[DetectionOut] = []

    model_config = {"from_attributes": True}


class VideoDetail(VideoOut):
    clips: List[ClipOut] = []
    events: List[EventOut] = []

    model_config = {"from_attributes": True}


class DashboardStats(BaseModel):
    total_videos: int
    processing_jobs: int
    completed_videos: int
    total_detections: int
    recent_videos: List[VideoOut] = []
