import os
import pytest

from helpers import ffmpeg_available, make_test_video


@ffmpeg_available
def test_scene_detection_returns_segments(tmp_path):
    from app.video.scene_detection import detect_scenes

    video = make_test_video(str(tmp_path / "scene.mp4"), duration_sec=3.0)
    segments = detect_scenes(video)
    assert isinstance(segments, list)
    assert len(segments) >= 1
    for start, end in segments:
        assert end > start
        assert end - start >= 0.5


def test_pipeline_fails_gracefully_on_missing_video(tmp_path):
    """Processing an invalid/missing video must raise rather than hang."""
    from app.video.pipeline import run_pipeline

    missing = str(tmp_path / "does_not_exist.mp4")
    with pytest.raises(Exception):
        run_pipeline(missing, video_id=1, job_id=1, video_public_name="video_1")


def test_detection_model_graceful_when_unavailable():
    """When ultralytics (or the model file) is unavailable, detection must
    gracefully degrade to no detections rather than fabricating results."""
    from app.vision.tracker import DetectionModel

    # A nonexistent model file path -> model cannot load (available() False)
    m = DetectionModel("models/definitely_missing_model.pt")
    # Regardless of whether ultralytics is importable, `detect` must never
    # raise on an unavailable model.
    assert m.detect(None) == []
