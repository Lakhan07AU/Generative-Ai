import subprocess
import json
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VideoMetadata:
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    nb_frames: Optional[int] = None


def ffprobe_metadata(video_path: str) -> VideoMetadata:
    """Extract video metadata using ffprobe."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    meta = VideoMetadata()
    if "format" in data and "duration" in data["format"]:
        try:
            meta.duration = float(data["format"]["duration"])
        except (TypeError, ValueError):
            pass

    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            meta.width = int(stream.get("width") or 0)
            meta.height = int(stream.get("height") or 0)
            meta.codec = stream.get("codec_name") or ""
            fps_str = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/0"
            try:
                num, den = fps_str.split("/")
                meta.fps = float(num) / float(den) if float(den) else 0.0
            except (ValueError, ZeroDivisionError):
                meta.fps = 0.0
            if "nb_frames" in stream:
                try:
                    meta.nb_frames = int(stream["nb_frames"])
                except (TypeError, ValueError):
                    meta.nb_frames = None
            break
    return meta


def extract_frame(video_path: str, timestamp: float, output_path: str) -> None:
    """Extract a single frame at a timestamp (seconds) using ffmpeg."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{timestamp:.3f}",
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def extract_clip(
    video_path: str,
    start_time: float,
    end_time: float,
    output_path: str,
    vf_scale: str = "1280:-2",
) -> None:
    """Extract a clip segment using ffmpeg (re-encode for consistent seeking)."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    duration = max(0.0, end_time - start_time)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_time:.3f}",
        "-t", f"{duration:.3f}",
        "-i", video_path,
        "-vf", f"scale={vf_scale}",
        "-an",
        "-c", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False
