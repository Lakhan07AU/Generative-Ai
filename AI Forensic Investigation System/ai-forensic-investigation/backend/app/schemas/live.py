from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class LiveStartRequest(BaseModel):
    """Parameters for starting a live capture session."""

    # "webrtc" | "simulation" | "file" | "droidcam_usb" | "webcam" | "ipcam"
    transport: str = "webrtc"
    fps_target: Optional[float] = None
    video_path: Optional[str] = None
    # OpenCV capture device index for the "webcam" / "droidcam_usb" transports.
    device_index: Optional[int] = None
    # Network stream URL for the "ipcam" transport (a phone as an IP camera),
    # e.g. http://<phone-ip>:8080/video or rtsp://<phone-ip>:554/...
    stream_url: Optional[str] = None
    buffer_window_seconds: Optional[float] = None
    buffer_max_frames: Optional[int] = None


class VlmAnalyzeRequest(BaseModel):
    """Body for a manual live VLM observation request (Phase 4)."""

    trigger: str = "manual"


class CameraSessionOut(BaseModel):
    id: int
    camera_id: int
    status: str
    transport: str
    fps_target: Optional[float] = None
    started_by_user_id: Optional[int] = None
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    error: Optional[str] = None
    frames_received: int = 0
    frames_sampled: int = 0
    frames_buffered: int = 0
    latest_frame_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class LiveStatusOut(BaseModel):
    camera_id: int
    camera_name: Optional[str] = None
    session_id: Optional[int] = None
    active: bool = False
    status: str = "OFFLINE"
    transport: Optional[str] = None
    fps_target: Optional[float] = None
    window_seconds: Optional[float] = None
    max_frames: Optional[int] = None
    source_health: Optional[dict] = None
    frames_received: int = 0
    frames_sampled: int = 0
    frames_rejected: int = 0
    frames_decimated: int = 0
    max_frame_bytes: int = 0
    frames_buffered: int = 0
    buffer_start: Optional[float] = None
    buffer_end: Optional[float] = None
    started_by_user_id: Optional[int] = None
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    updated_at: Optional[str] = None
    error: Optional[str] = None
    detection_enabled: bool = False
    detection_error: Optional[str] = None
    detection_metrics: Optional[dict] = None
    detection_recent_count: int = 0
    tracking_enabled: bool = False
    active_tracks: int = 0
    total_events: int = 0
    vlm_enabled: bool = False
    vlm_last_error: Optional[str] = None
    vlm_requests: int = 0
    vlm_observations: int = 0
    evidence_enabled: bool = False
    evidence_last_error: Optional[str] = None
    evidence_captured: int = 0
    evidence_indexed: int = 0
    evidence_failed: int = 0


class LiveSummaryOut(BaseModel):
    sessions: List[LiveStatusOut]
    camera_id: int
    available: bool