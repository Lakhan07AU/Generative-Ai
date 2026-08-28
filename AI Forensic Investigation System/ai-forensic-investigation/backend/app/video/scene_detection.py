import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def detect_scenes(video_path: str) -> list[tuple[float, float]]:
    """Detect scene boundaries and return a list of (start, end) segments in seconds.

    Uses PySceneDetect's ContentDetector. Falls back to a naive fixed-length split
    if PySceneDetect or FFmpeg is unavailable so the pipeline never silently dies.
    """
    try:
        from scenedetect import detect, ContentDetector

        scenes = detect(video_path, ContentDetector(threshold=settings.SCENE_SENSITIVITY))
        segments = []
        for sc in scenes:
            start = sc[0].get_seconds()
            end = sc[1].get_seconds()
            if end - start >= 0.5:
                segments.append((start, end))
        if segments:
            logger.info("Scene detection found %d segments", len(segments))
            return segments
        logger.info("No scene changes detected; using fallback splitting")
        return _fallback_split(video_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PySceneDetect failed (%s); using fallback splitting", exc)
        return _fallback_split(video_path)


def _fallback_split(video_path: str) -> list[tuple[float, float]]:
    """Naive fixed-length splitting based on ffprobe duration."""
    from app.video.ffmpeg_utils import ffprobe_metadata

    meta = ffprobe_metadata(video_path)
    duration = meta.duration
    if duration <= 0:
        return []
    chunk = 5.0
    segments = []
    start = 0.0
    while start < duration:
        end = min(start + chunk, duration)
        segments.append((start, end))
        start = end
    # Keep a reasonable number
    if len(segments) > settings.MAX_CLIPS:
        segments = segments[: settings.MAX_CLIPS]
    return segments
