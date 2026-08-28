"""Test helpers that do NOT depend on pytest fixtures.

Kept separate from conftest.py so individual test modules can import them
directly as a regular module.
"""

import os
import shutil
import subprocess

import pytest


def _has_ffmpeg():
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


ffmpeg_available = pytest.mark.skipif(
    not _has_ffmpeg(), reason="ffmpeg/ffprobe not available on this machine"
)


def _has_minio():
    try:
        from app.storage.service import storage

        storage.ensure_buckets()
        storage.client.list_buckets()
        return True
    except Exception:
        return False


minio_available = pytest.mark.skipif(
    not _has_minio(), reason="MinIO not available on this machine"
)


def make_test_video(
    path: str,
    duration_sec: float = 2.0,
    width: int = 320,
    height: int = 240,
    fps: int = 10,
):
    """Generate a real test video using ffmpeg (testsrc pattern)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"testsrc=size={width}x{height}:rate={fps}:duration={duration_sec}",
        "-pix_fmt", "yuv420p",
        path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return path
