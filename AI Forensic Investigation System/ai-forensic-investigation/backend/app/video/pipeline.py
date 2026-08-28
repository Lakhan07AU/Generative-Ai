import os
import logging
from datetime import datetime

import cv2
import numpy as np

from app.core.config import settings
from app.storage.service import storage
from app.video.ffmpeg_utils import ffprobe_metadata, extract_clip, extract_frame
from app.video.scene_detection import detect_scenes
from app.vision.tracker import DetectionModel, IoUTracker

logger = logging.getLogger(__name__)


def _mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def run_pipeline(video_path: str, video_id: int, job_id: int, video_public_name: str) -> dict:
    """Run the full video processing pipeline for a single uploaded video.

    Returns a dict with the results summary:
        metadata, segments, clips (list of dicts), detections (count),
        events, thumbnails.
    Raises exceptions on failure - the caller marks the job as FAILED.
    """
    _mkdir(settings.DATA_DIR)
    work_dir = os.path.join(settings.DATA_DIR, "work", f"video_{video_id}")
    _mkdir(work_dir)
    clip_dir = os.path.join(work_dir, "clips")
    frame_dir = os.path.join(work_dir, "frames")
    thumb_dir = os.path.join(work_dir, "thumbs")
    _mkdir(clip_dir)
    _mkdir(frame_dir)
    _mkdir(thumb_dir)

    # ---- STAGE: METADATA ----
    metadata = ffprobe_metadata(video_path)

    # ---- STAGE: SCENE_DETECTION ----
    segments = detect_scenes(video_path)

    # ---- Load detection model once for the whole video ----
    detection_model = DetectionModel(settings.YOLO_MODEL)
    if not detection_model.available():
        logger.warning("YOLO model not available; detections will be skipped")

    tracker = IoUTracker()

    clips = []
    total_detections = 0
    events = []
    thumbnails = []

    # ---- STAGE: CLIP_EXTRACTION + DETECTION + TRACKING ----
    for idx, (start, end) in enumerate(segments, start=1):
        public_id = f"CLIP-{video_id:04d}-{idx:03d}"
        clip_file = os.path.join(clip_dir, f"clip_{idx}.mp4")
        thumb_file = os.path.join(thumb_dir, f"clip_{idx}.jpg")

        # Extract clip segment
        try:
            extract_clip(video_path, start, end, clip_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Clip extraction failed for segment %d: %s", idx, exc)
            continue

        # Extract a representative keyframe (middle of clip)
        key_time = (start + end) / 2.0
        key_frame_file = os.path.join(frame_dir, f"frame_{idx}.jpg")
        try:
            extract_frame(video_path, key_time, key_frame_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Keyframe extraction failed for segment %d: %s", idx, exc)
            key_frame_file = None

        # Create thumbnail from keyframe
        thumb_path = None
        if key_frame_file and os.path.exists(key_frame_file):
            thumb_path = thumb_file
            _mkdir(os.path.dirname(thumb_file))
            try:
                img = cv2.imread(key_frame_file)
                if img is not None:
                    h, w = img.shape[:2]
                    scale = 480 / max(h, w) if max(h, w) > 0 else 1.0
                    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
                    thumb_img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    cv2.imwrite(thumb_file, thumb_img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                else:
                    thumb_path = None
            except Exception as exc:  # noqa: BLE001
                logger.warning("Thumbnail generation failed: %s", exc)
                thumb_path = None

        # Run detection + tracking over frames sampled from the clip
        clip_detections = []
        if detection_model.available() and os.path.exists(clip_file):
            clip_detections = _run_detection_tracking(
                clip_file,
                video_id,
                start,
                detection_model,
                tracker,
                frame_dir,
                idx,
            )
            total_detections += len(clip_detections)

        # Persist the clip
        clip_storage_path = _upload_clip_to_storage(
            clip_file, video_public_name, idx, clip_file
        )
        thumb_storage_path = None
        if thumb_path and os.path.exists(thumb_path):
            thumb_storage_path = storage.put_file(
                "thumbnails",
                thumb_path,
                storage.unique_name(f"thumb_{video_public_name}", ".jpg"),
                content_type="image/jpeg",
            )

        clips.append(
            {
                "public_id": public_id,
                "start_time": round(start, 3),
                "end_time": round(end, 3),
                "storage_path": clip_storage_path,
                "thumbnail_path": thumb_storage_path,
                "detections": clip_detections,
            }
        )

    # ---- STAGE: EVENTS (simple heuristic summaries) ----
    events = _build_events(video_id, clips)

    return {
        "metadata": metadata.__dict__,
        "segments": [(round(s, 3), round(e, 3)) for s, e in segments],
        "clips": clips,
        "events": events,
        "total_detections": total_detections,
        "thumbnails": thumbnails,
    }


def _run_detection_tracking(
    clip_file: str,
    video_id: int,
    clip_start: float,
    detection_model: DetectionModel,
    tracker: IoUTracker,
    frame_dir: str,
    clip_idx: int,
) -> list[dict]:
    """Open the clip, sample frames, run YOLO + IoU tracking, return detections."""
    cap = cv2.VideoCapture(clip_file)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    detections_out = []
    frame_number = 0
    step = max(1, int(round(fps / 2.0)))  # sample ~2 fps

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_number % step == 0:
            frame_time = clip_start + (frame_number / fps if fps else 0.0)
            dets = detection_model.detect(frame)
            annotated = tracker.update(dets, frame_number)
            for d in annotated:
                detections_out.append(
                    {
                        "label": d["label"],
                        "bbox": d["bbox"],
                        "confidence": d["confidence"],
                        "frame_number": frame_number,
                        "timestamp": round(frame_time, 3),
                        "tracking_id": d.get("tracking_id"),
                    }
                )
        frame_number += 1

    cap.release()
    return detections_out


def _upload_clip_to_storage(local_file: str, video_public_name: str, idx: int, clip_file: str) -> str | None:
    try:
        ext = os.path.splitext(clip_file)[1] or ".mp4"
        return storage.put_file(
            "clips",
            local_file,
            storage.unique_name(f"clip_{video_public_name}_{idx}", ext),
            content_type="video/mp4",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Clip storage upload failed: %s", exc)
        return None


def _build_events(video_id: int, clips: list[dict]) -> list[dict]:
    """Build lightweight, purely descriptive events from detection labels.

    Note: These are observational summaries only. The prototype deliberately
    does NOT infer human intent, identity, or facial recognition.
    """
    events = []
    for clip in clips:
        people_count = sum(
            1 for d in clip["detections"] if d["label"].lower() == "person"
        )
        if people_count > 0:
            events.append(
                {
                    "event_type": "person_present",
                    "description": f"{people_count} person(s) detected in segment",
                    "start_time": clip["start_time"],
                    "end_time": clip["end_time"],
                    "confidence": 0.9,
                    "public_id": clip["public_id"],
                }
            )
    return events
