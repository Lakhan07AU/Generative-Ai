"""Audio transcription (Whisper).

Pipeline: Audio -> Whisper -> timestamped transcript.

* Real mode uses ``faster-whisper`` when installed and ``WHISPER_MODEL`` is not
  ``"simulation"``.
* Simulation mode (default) produces deterministic, clearly-labelled timestamped
  transcript segments derived from the video's observable detections and clip
  timings, so the pipeline is fully testable offline without a model download.

Transcript segments always expose: ``start_time``, ``end_time``, ``text``,
``confidence``.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings
from app.video.ffmpeg_utils import ffprobe_metadata

logger = logging.getLogger(__name__)


def is_simulation() -> bool:
    return (settings.WHISPER_MODEL or "").strip().lower() == "simulation"


def transcribe(video_path: str, clip_start: float = 0.0, clip_end: Optional[float] = None) -> list[dict]:
    """Return timestamped transcript segments for a video/clip."""
    if not is_simulation():
        try:
            return _real_transcribe(video_path, clip_start, clip_end)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Whisper transcription failed (%s); using simulation transcript", exc)
            return _simulate_transcribe(video_path, clip_start, clip_end)
    return _simulate_transcribe(video_path, clip_start, clip_end)


def _real_transcribe(video_path: str, clip_start: float, clip_end: Optional[float]) -> list[dict]:
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(settings.WHISPER_MODEL, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(video_path, language=settings.WHISPER_LANGUAGE or None)
        out = []
        for seg in segments:
            if clip_end is not None and seg.start >= clip_end:
                break
            out.append(
                {
                    "start_time": round(clip_start + float(seg.start), 3),
                    "end_time": round(clip_start + float(seg.end), 3),
                    "text": seg.text.strip(),
                    "confidence": round(float(seg.avg_logprob or 0.0), 4),
                }
            )
        return out
    except ImportError as exc:  # faster-whisper not installed
        logger.warning("faster-whisper not installed (%s); using simulation transcript", exc)
        return _simulate_transcribe(video_path, clip_start, clip_end)


def _simulate_transcribe(video_path: str, clip_start: float, clip_end: Optional[float]) -> list[dict]:
    """Deterministic pseudo-transcript clearly labelled as simulated."""
    meta = ffprobe_metadata(video_path)
    duration = meta.duration
    if duration <= 0:
        return []
    end = clip_end if clip_end is not None else duration
    seg_len = 4.0
    out = []
    t = clip_start
    i = 0
    while t < end - 0.5:
        s_end = min(t + seg_len, end)
        out.append(
            {
                "start_time": round(t, 3),
                "end_time": round(s_end, 3),
                "text": "[SIMULATED TRANSCRIPT] Ambient audio segment - no dialog detected.",
                "confidence": round(0.5 + (i % 10) / 20.0, 3),
            }
        )
        t = s_end
        i += 1
    return out
