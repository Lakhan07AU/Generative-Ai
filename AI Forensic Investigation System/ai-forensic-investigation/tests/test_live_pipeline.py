"""Phase 1 pipeline unit tests: sampler, ingestion, rolling buffer, source."""

import threading
import time

import numpy as np
import pytest

from app.live.rolling_buffer import RollingFrameBuffer
from app.live.sampler import FrameSampler
from app.live.ingestion import FrameIngestion
from app.live.source import LiveCameraSource


def make_frame(w: int = 32, h: int = 32) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


# ------------------------------------------------------------------ sampler


def test_sampler_first_frame_always_accepted():
    s = FrameSampler(target_fps=5.0)
    assert s.accept(0.0) is True
    assert s.sampled == 1


def test_sampler_decimates_to_target_rate():
    s = FrameSampler(target_fps=5.0)  # period = 0.2s
    timestamps = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    results = [s.accept(t) for t in timestamps]
    assert results == [True, False, True, False, True, False]
    assert s.sampled == 3
    assert s.decimated == 3


def test_sampler_configurable_target():
    s = FrameSampler(target_fps=10.0)  # period = 0.1s
    results = [s.accept(t) for t in [0.0, 0.04, 0.10, 0.15, 0.20]]
    assert results == [True, False, True, False, True]


def test_sampler_rejects_invalid_target():
    with pytest.raises(ValueError):
        FrameSampler(target_fps=0)
    with pytest.raises(ValueError):
        FrameSampler(target_fps=-1)


def test_sampler_handles_backwards_timestamp():
    s = FrameSampler(target_fps=5.0)
    assert s.accept(10.0) is True
    assert s.accept(9.0) is True  # clock jitter: must not stall
    assert s.sampled == 2


def test_sampler_resets():
    s = FrameSampler(target_fps=5.0)
    s.accept(0.0)
    s.accept(0.5)
    s.reset()
    assert s.sampled == 0 and s.decimated == 0
    assert s.accept(0.0) is True


# ----------------------------------------------------------------- ingestion


def _ingestion(sampler=None, cap=30.0, max_bytes=1_000_000, clock=None):
    return FrameIngestion(
        sampler=sampler or FrameSampler(target_fps=5.0),
        buffer=RollingFrameBuffer(window_seconds=1000.0, max_frames=10_000, clock=clock),
        source_fps_cap=cap,
        max_frame_bytes=max_bytes,
    )


def test_ingestion_forwards_sampled_frames_only():
    ing = _ingestion(cap=100.0, clock=fake_clock_at(1000.0))
    ts = [t * 0.05 for t in range(40)]  # 20 fps for 2s
    for t in ts:
        ing.ingest(make_frame(), t)
    assert ing.received == 40
    assert ing.sampled == ing.buffer.count()
    assert 8 <= ing.sampled <= 12  # ~10 at target 5fps over 2s
    assert ing.rejected == 0


def test_ingestion_rate_cap_drops_bursts():
    ing = _ingestion(cap=10.0, clock=fake_clock_at(1000.0))  # min interval = 0.1s
    # 50 frames @ 200fps -> only every 0.1s+ accepted (about 10)
    for i in range(50):
        ing.ingest(make_frame(), i * 0.005)
    assert ing.received == 50
    assert ing.rejected >= 35
    assert ing.sampled <= ing.received - ing.rejected


def test_ingestion_rejects_oversized_frames():
    ing = _ingestion(max_bytes=1024, clock=fake_clock_at(1000.0))
    blob = b"x" * 2048
    assert ing.ingest(blob, 0.0) is False
    assert ing.rejected == 1
    assert ing.buffer.count() == 0


def test_default_frame_cap_admits_a_1080p_and_4k_frame():
    """Regression: the 4 MB default silently starved every 1080p source.

    A 1920x1080 BGR frame is ~6.2 MB, so each frame was rejected as oversized:
    the session still reported LIVE and counted ``received`` frames, but
    nothing was ever sampled, so YOLO, tracking and evidence never ran.
    """
    from app.core.config import settings

    frame_1080p = np.zeros((1080, 1920, 3), dtype=np.uint8)  # 6_220_800 bytes
    frame_4k = np.zeros((2160, 3840, 3), dtype=np.uint8)  # 24_883_200 bytes
    assert frame_1080p.nbytes > 4 * 1024 * 1024
    assert settings.LIVE_MAX_FRAME_BYTES > frame_4k.nbytes

    ing = _ingestion(max_bytes=settings.LIVE_MAX_FRAME_BYTES, clock=fake_clock_at(1000.0))
    for i, frame in enumerate((frame_1080p, frame_4k)):
        assert ing.ingest(frame, i * 0.5) is True, f"frame {i} was rejected as oversized"
    assert ing.rejected == 0
    assert ing.sampled == 2
    assert ing.buffer.count() == 2


def test_rejection_counters_are_reported_in_the_session_snapshot():
    """A starved session must be diagnosable from status, not silent."""
    from app.live.manager import LiveSessionRuntime

    runtime = LiveSessionRuntime(
        camera_id=1, camera_name="probe", started_by_user_id=1, transport="ipcam"
    )
    big = np.zeros((1080, 1920, 3), dtype=np.uint8)
    small = np.zeros((8, 8, 3), dtype=np.uint8)
    # The cap is read by the ingestion object, so shrink it there.
    runtime.ingestion._max_frame_bytes = 1024
    runtime.ingestion.ingest(big, 1000.0)
    runtime.ingestion.ingest(small, 1000.5)

    snap = runtime.snapshot()
    assert snap["frames_rejected"] == 1
    assert snap["frames_sampled"] == 1
    assert snap["max_frame_bytes"] == 1024


def test_ingestion_rejects_invalid_params():
    with pytest.raises(ValueError):
        FrameIngestion(sampler=FrameSampler(5.0), buffer=RollingFrameBuffer(), source_fps_cap=0)
    with pytest.raises(ValueError):
        FrameIngestion(sampler=FrameSampler(5.0), buffer=RollingFrameBuffer(), max_frame_bytes=-1)


# ------------------------------------------------------------- rolling buffer


def fake_clock_at(value):
    return lambda: value


def test_rolling_buffer_max_frames_evicts_oldest():
    buf = RollingFrameBuffer(window_seconds=1000.0, max_frames=10, clock=fake_clock_at(100.0))
    for i in range(30):
        buf.append(make_frame(), 100.0 + i * 0.1)
    assert buf.count() == 10
    oldest = buf.oldest_timestamp
    assert oldest == pytest.approx(100.0 + 20 * 0.1)


def test_rolling_buffer_window_eviction_is_deterministic():
    buf = RollingFrameBuffer(window_seconds=1.0, max_frames=100, clock=fake_clock_at(100.0))
    buf.append(make_frame(), 98.0)  # older than cutoff (99.0) -> evicted on append
    assert buf.count() == 0
    assert buf.trim() == 0
    buf.append(make_frame(), 99.5)
    buf.append(make_frame(), 100.2)
    assert buf.count() == 2
    assert buf.oldest_timestamp == pytest.approx(99.5)


def test_rolling_buffer_range_query():
    buf = RollingFrameBuffer(window_seconds=1000.0, max_frames=100, clock=fake_clock_at(100.0))
    for i in range(10):
        buf.append(make_frame(), 100.0 + i)
    window = buf.frames_between(103.0, 105.0)
    assert [e.timestamp for e in window] == [103.0, 104.0, 105.0]


def test_rolling_buffer_latest_and_snapshot_order():
    buf = RollingFrameBuffer(window_seconds=1000.0, max_frames=100, clock=fake_clock_at(100.0))
    for i in range(5):
        buf.append(f"frame-{i}", 100.0 + i)
    assert buf.latest().frame == "frame-4"
    assert [e.frame for e in buf.snapshot()] == ["frame-0", "frame-1", "frame-2", "frame-3", "frame-4"]
    assert [e.frame for e in buf.snapshot(limit=2)] == ["frame-3", "frame-4"]


def test_rolling_buffer_concurrent_append_safe():
    buf = RollingFrameBuffer(window_seconds=1000.0, max_frames=500, clock=fake_clock_at(100.0))
    errors = []
    lock = threading.Lock()

    def worker(base):
        try:
            for i in range(200):
                buf.append(make_frame(), 100.0 + i * 0.001 + base)
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t * 0.0001,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert 0 < buf.count() <= 500
    # FIFO sequence order is the invariant (arrival order is globally sequenced)
    seqs = [e.sequence for e in buf.snapshot()]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_rolling_buffer_validation():
    with pytest.raises(ValueError):
        RollingFrameBuffer(window_seconds=0)
    with pytest.raises(ValueError):
        RollingFrameBuffer(max_frames=0)


# -------------------------------------------------------------------- source


def test_live_source_forwards_to_ingestion():
    ing = _ingestion(cap=100.0, clock=fake_clock_at(1050.0))
    src = LiveCameraSource(ingestion=ing, clock=lambda: 50.0)
    for _ in range(10):
        src.push(make_frame())
    assert src.pushed == 10
    assert ing.received == 10
    # identical timestamps from the fake clock -> sampler keeps only the first
    assert ing.buffer.count() == 1
    assert ing.sampled == 1


def test_live_source_counts_dropped_when_unbound():
    src = LiveCameraSource(ingestion=None, clock=lambda: 50.0)
    assert src.push(make_frame()) is False
    assert src.dropped == 1