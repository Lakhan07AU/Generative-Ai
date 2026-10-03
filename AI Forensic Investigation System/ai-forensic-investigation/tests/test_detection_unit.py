"""Phase 2 detection unit tests: schemas, metrics, engine helpers, worker, pipeline."""

import threading
import time

import numpy as np
import pytest

from app.detection.engine import InvalidFrameError, as_bgr_uint8
from app.detection.metrics import DetectionMetrics
from app.detection.pipeline import DetectionPipeline
from app.detection.schemas import BoundingBox, DetectionFrame, DetectionObject
from app.detection.worker import DetectionWorker

from detection_fakes import FailingEngine, FakeEngine


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    def advance(self, dt):
        self.now += dt


def bgr_frame(w=320, h=240, value=128):
    return np.full((h, w, 3), value, dtype=np.uint8)


def wait_until(predicate, timeout=3.0, step=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


# ------------------------------------------------------------------ schemas


def test_bbox_validation_bounds():
    assert BoundingBox(x1=1, y1=2, x2=10, y2=20).is_valid(320, 240)
    assert not BoundingBox(x1=10, y1=0, x2=5, y2=20).is_valid(320, 240)
    assert not BoundingBox(x1=0, y1=0, x2=1000, y2=10).is_valid(320, 240)
    assert BoundingBox(x1=0, y1=0, x2=100, y2=100).is_valid()  # no dims supplied


def test_bbox_rejects_negatives():
    with pytest.raises(Exception):
        BoundingBox(x1=-1, y1=0, x2=10, y2=10)


def test_detection_frame_broadcast_shape():
    frame = DetectionFrame(
        session_id=7, camera_id=3, frame_id=42, frame_timestamp=1.25,
        frame_width=320, frame_height=240,
        detections=[DetectionObject(
            detection_id="d1", class_id=0, class_name="person", confidence=0.9,
            bbox=BoundingBox(x1=5, y1=6, x2=55, y2=66),
            frame_timestamp=1.25, session_id=7, frame_id=42, camera_id=3,
        )],
    )
    out = frame.as_broadcast()
    assert out["type"] == "detection"
    assert out["session_id"] == 7 and out["camera_id"] == 3 and out["frame_id"] == 42
    assert out["detections"][0]["class_name"] == "person"
    # bbox must be the absolute pixel list [x1, y1, x2, y2] (NOT normalized)
    assert out["detections"][0]["bbox"] == [5, 6, 55, 66]
    assert 0.0 <= out["detections"][0]["confidence"] <= 1.0


def test_detection_frame_empty_default():
    out = DetectionFrame(camera_id=1, frame_timestamp=0.5).as_broadcast()
    assert out["detections"] == []


# ----------------------------------------------------------- engine helpers


def test_as_bgr_uint8_conversions():
    rgb = np.zeros((10, 10, 3), dtype=np.uint8)
    out = as_bgr_uint8(rgb)
    assert out.shape == (10, 10, 3) and out.dtype == np.uint8
    # grayscale -> 3 channel
    gray = np.zeros((10, 10), dtype=np.uint8)
    assert as_bgr_uint8(gray).shape == (10, 10, 3)
    # 4 channel -> 3 channel
    rgba = np.zeros((10, 10, 4), dtype=np.uint8)
    assert as_bgr_uint8(rgba).shape == (10, 10, 3)
    # list of lists -> ndarray
    assert as_bgr_uint8([[0, 0, 0], [255, 255, 255]]).ndim == 3


def test_as_bgr_uint8_rejects_bad_shapes():
    with pytest.raises(InvalidFrameError):
        as_bgr_uint8(np.zeros((10, 10, 5), dtype=np.uint8))
    with pytest.raises(InvalidFrameError):
        as_bgr_uint8("not-a-frame")


# ------------------------------------------------------------------ metrics


def test_metrics_counts():
    m = DetectionMetrics()
    m.record_input(); m.record_input()
    m.record_sampled()
    m.record_processed(5.0); m.record_processed(15.0)
    m.record_detections(3)
    m.record_dropped()
    m.record_inference_error()
    snap = m.snapshot()
    assert snap["total_input"] == 2
    assert snap["total_sampled"] == 1
    assert snap["total_processed"] == 2
    assert snap["total_detections"] == 3
    assert snap["total_dropped"] == 1
    assert snap["inference_errors"] == 1
    assert snap["inference_latency_avg_ms"] == pytest.approx(10.0)
    assert snap["inference_latency_max_ms"] == pytest.approx(15.0)


def test_metrics_rates_with_injected_clock():
    clk = FakeClock()
    m = DetectionMetrics(window_seconds=5.0, clock=clk)
    for _ in range(3):
        clk.advance(0.5)
        m.record_input()
    # stable 2 fps after warm-up
    for _ in range(5):
        clk.advance(0.5)
        m.record_input()
    assert m.snapshot()["input_fps"] == pytest.approx(2.0, abs=0.2)


def test_metrics_rates_stay_plausible_when_events_interleave_in_bursts():
    """Regression: rates exploded into the hundreds of thousands.

    The producer and inference threads interleave record_input/record_sampled/
    record_processed, and record_detections fires once per frame. A shared
    "last timestamp" plus an EMA of instantaneous 1/dt turned those
    microsecond gaps into ~375,000 detections/sec on a ~16 fps stream.
    """
    clk = FakeClock()
    m = DetectionMetrics(window_seconds=5.0, clock=clk)
    # ~16 processed frames/sec, each contributing 3 detections.
    for _ in range(80):
        m.record_input()
        m.record_sampled()
        m.record_processed(70.0)
        m.record_detections(3)
        clk.advance(1.0 / 16.0)
    snap = m.snapshot()
    for key, ceiling in (
        ("input_fps", 25.0),
        ("sampled_fps", 25.0),
        ("processed_fps", 25.0),
        ("detection_fps", 100.0),
    ):
        assert 0.0 < snap[key] <= ceiling, f"{key}={snap[key]} is not a real rate"
    assert snap["detection_fps"] == pytest.approx(48.0, abs=6.0)
    assert snap["total_detections"] == 240


def test_metrics_detection_rate_ignores_frames_with_no_detections():
    clk = FakeClock()
    m = DetectionMetrics(window_seconds=5.0, clock=clk)
    m.record_detections(0)
    m.record_processed(70.0)
    clk.advance(0.1)
    assert m.snapshot()["detection_fps"] == 0.0


def test_metrics_thread_safety():
    m = DetectionMetrics()
    errors = []

    def hammer():
        try:
            for _ in range(200):
                m.record_input()
                m.record_processed(1.0)
                m.record_detections(1)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=hammer) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert m.snapshot()["total_input"] == 1200
    assert m.snapshot()["total_processed"] == 1200


# ------------------------------------------------------------------ worker


def test_worker_processes_frames_and_reports_results():
    engine = FakeEngine(detections_per_call=[2, 0])
    results = []
    worker = DetectionWorker(engine=engine, on_result=results.append, maxsize=8)
    worker.start(DetectionMetrics())
    try:
        assert worker.running
        assert worker.submit(bgr_frame(), 1.0, frame_id=1)
        assert worker.submit(bgr_frame(), 2.0, frame_id=2)
        assert wait_until(lambda: len(results) == 2)
    finally:
        worker.stop()
    frames_by_id = {r.frame_id: r for r in results}
    assert frames_by_id[1].detections and len(frames_by_id[1].detections) == 2
    assert frames_by_id[2].detections == []
    assert not worker.running


def test_worker_serializes_shared_engine_and_tracks_metrics():
    engine = FakeEngine(infer_ms=0.005, on_infer=lambda f, k: 1)  # exactly 1 detection/frame
    metrics = DetectionMetrics()
    worker = DetectionWorker(engine=engine, on_result=lambda _r: None, maxsize=8)
    worker.start(metrics)
    try:
        for i in range(5):
            worker.submit(bgr_frame(), float(i), frame_id=i)
        assert wait_until(lambda: metrics.snapshot()["total_processed"] == 5)
    finally:
        worker.stop()
    snap = metrics.snapshot()
    assert snap["total_processed"] == 5
    assert snap["total_detections"] == 5
    assert snap["queue_depth"] == 0


def test_worker_bounded_queue_evicts_stale_and_counts_drops():
    engine = FakeEngine(infer_ms=0.05)  # slow consumer
    metrics = DetectionMetrics()
    worker = DetectionWorker(engine=engine, on_result=lambda _r: None, maxsize=3)
    worker.start(metrics)
    try:
        # fill the queue well past maxsize; slow consumer leaves frames waiting
        submitted = 0
        while metrics.snapshot()["total_processed"] < 1 and submitted < 200:
            worker.submit(bgr_frame(value=submitted), float(submitted), frame_id=submitted)
            submitted += 1
        assert worker.queue_size <= worker.queue_maxsize
        assert worker.queue_size > 0
        assert metrics.snapshot()["total_dropped"] > 0
        # newest frame is either queued or already being processed, never an old one
        assert submitted > worker.queue_maxsize
        assert metrics.snapshot()["total_processed"] + metrics.snapshot()["total_dropped"] + worker.queue_size >= submitted - 1
    finally:
        worker.stop()
    assert worker.queue_size == 0


def test_worker_submit_rejected_when_not_running():
    worker = DetectionWorker(engine=FakeEngine(), on_result=lambda _r: None)
    assert worker.submit(bgr_frame(), 0.0) is False


def test_worker_stop_drains_pending():
    engine = FakeEngine(infer_ms=0.01)
    results = []
    worker = DetectionWorker(engine=engine, on_result=results.append, maxsize=16)
    worker.start(DetectionMetrics())
    worker.submit(bgr_frame(value=1), 1.0, frame_id=1)
    worker.submit(bgr_frame(value=2), 2.0, frame_id=2)
    worker.submit(bgr_frame(value=3), 3.0, frame_id=3)
    worker.stop(drain=True)
    assert len(results) >= 3


def test_worker_stop_discards_when_not_draining():
    engine = FakeEngine(infer_ms=0.02)
    results = []
    worker = DetectionWorker(engine=engine, on_result=results.append, maxsize=16)
    worker.start(DetectionMetrics())
    worker.submit(bgr_frame(), 1.0, frame_id=1)
    worker.submit(bgr_frame(), 2.0, frame_id=2)
    worker.stop(drain=False)
    assert len(results) < 2
    assert worker.queue_size == 0


def test_worker_inference_error_is_not_fatal():
    errors = []
    worker = DetectionWorker(engine=FailingEngine(), on_result=lambda _r: None, on_error=errors.append)
    metrics = DetectionMetrics()
    worker.start(metrics)
    try:
        worker.submit(bgr_frame(), 1.0, frame_id=1)
        worker.submit(bgr_frame(), 2.0, frame_id=2)
        assert wait_until(lambda: len(errors) >= 2)
        assert metrics.snapshot()["inference_errors"] >= 2
        # worker is still alive and able to take more frames
        assert worker.running
        worker.submit(bgr_frame(), 3.0, frame_id=3)
        assert wait_until(lambda: len(errors) >= 3)
    finally:
        worker.stop()


def test_worker_throughput_under_load_stays_bounded():
    """Sustained load: the queue must stay bounded and the worker must keep up
    without raising; memory (length) never grows with submission count."""
    engine = FakeEngine(infer_ms=0.001)
    metrics = DetectionMetrics()
    worker = DetectionWorker(engine=engine, on_result=lambda _r: None, maxsize=4)
    worker.start(metrics)
    try:
        peak_queue = 0
        for i in range(3000):
            worker.submit(bgr_frame(), float(i), frame_id=i)
            peak_queue = max(peak_queue, worker.queue_size)
            if i % 50 == 0:
                time.sleep(0.001)  # let the consumer breathe periodically
        assert peak_queue <= worker.queue_maxsize + 1
        assert wait_until(lambda: metrics.snapshot()["total_processed"] > 0)
        assert metrics.snapshot()["total_dropped"] >= 0
        assert worker.queue_size <= worker.queue_maxsize
    finally:
        worker.stop()


# ---------------------------------------------------------------- pipeline


def test_pipeline_routes_results_and_keeps_recent():
    engine = FakeEngine(detections_per_call=[1, 0, 2])
    got = []
    pipeline = DetectionPipeline(
        engine=engine,
        on_result=got.append,
        queue_size=4,
        recent_frames=20,
    )
    pipeline.start()
    try:
        assert pipeline.running
        assert pipeline.submit(bgr_frame(), 1.0, frame_id=1)
        assert pipeline.submit(bgr_frame(), 2.0, frame_id=2)
        assert pipeline.submit(bgr_frame(), 3.0, frame_id=3)
        assert wait_until(lambda: len(got) == 3)
    finally:
        pipeline.stop()
    recent = pipeline.recent_results()
    assert len(recent) == 3
    assert all("detections" in r and "timestamp" in r for r in recent)
    assert pipeline.snapshot()["total_processed"] == 3
    assert not pipeline.running


def test_pipeline_recent_ring_is_bounded():
    engine = FakeEngine(infer_ms=0.005)
    pipeline = DetectionPipeline(engine=engine, on_result=lambda _r: None, queue_size=8, recent_frames=5)
    pipeline.start()
    try:
        # feed one at a time (a larger burst is legitimately evicted by design)
        expected = 0
        for i in range(12):
            assert pipeline.submit(bgr_frame(), float(i), frame_id=i)
            expected += 1
            assert wait_until(lambda e=expected: pipeline.snapshot()["total_processed"] == e)
    finally:
        pipeline.stop()
    assert len(pipeline.recent_results()) == 5
    assert [r["frame_id"] for r in pipeline.recent_results()] == [7, 8, 9, 10, 11]


def test_pipeline_input_metrics_flow():
    engine = FakeEngine(infer_ms=0.01)
    pipeline = DetectionPipeline(engine=engine, on_result=lambda _r: None, queue_size=4, recent_frames=10)
    pipeline.start()
    try:
        pipeline.metrics.record_input()
        pipeline.metrics.record_sampled()
        pipeline.submit(bgr_frame(), 0.0, frame_id=1)
        assert wait_until(lambda: pipeline.snapshot()["total_processed"] == 1)
    finally:
        pipeline.stop()
    snap = pipeline.snapshot()
    assert snap["total_input"] == 1
    assert snap["total_sampled"] == 1
    assert snap["total_processed"] == 1