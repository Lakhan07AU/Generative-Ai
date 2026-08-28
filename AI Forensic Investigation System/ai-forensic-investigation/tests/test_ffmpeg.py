import os

from helpers import ffmpeg_available, make_test_video


@ffmpeg_available
def test_metadata_extraction(tmp_path):
    from app.video.ffmpeg_utils import ffprobe_metadata

    video = make_test_video(str(tmp_path / "meta.mp4"), duration_sec=1.0, width=320, height=240, fps=10)
    meta = ffprobe_metadata(video)
    assert meta.width == 320
    assert meta.height == 240
    assert meta.fps == 10.0 or abs(meta.fps - 10.0) < 1.0
    assert meta.duration > 0


@ffmpeg_available
def test_extract_clip_timestamps(tmp_path):
    from app.video.ffmpeg_utils import extract_clip, ffprobe_metadata

    video = make_test_video(str(tmp_path / "src.mp4"), duration_sec=3.0)
    out = str(tmp_path / "clip.mp4")
    extract_clip(video, 0.5, 2.5, out)
    assert os.path.exists(out)
    clip_meta = ffprobe_metadata(out)
    assert 1.5 <= clip_meta.duration <= 2.5


@ffmpeg_available
def test_extract_frame(tmp_path):
    from app.video.ffmpeg_utils import extract_frame
    import cv2

    video = make_test_video(str(tmp_path / "src.mp4"), duration_sec=1.0)
    frame_path = str(tmp_path / "frame.jpg")
    extract_frame(video, 0.5, frame_path)
    assert os.path.exists(frame_path)
    img = cv2.imread(frame_path)
    assert img is not None
