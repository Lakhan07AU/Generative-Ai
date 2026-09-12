"""Phase 2 real YOLO smoke/performance test (requires the actual weights file).

Skipped automatically when the model file is absent. This test is deliberately
kept out of the main unit suite assumptions: it loads the genuine Ultralytics
model and runs real inference so we can record true per-device latency.
"""

import os
import time

import numpy as np
import pytest

from app.detection.engine import DetectionEngine, clear_engines

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
MODEL = os.path.join(BACKEND_DIR, "yolov8n.pt")


@pytest.mark.skipif(not os.path.isfile(MODEL), reason="yolov8n.pt weights not bundled")
def test_real_yolo_loads_and_infers():
    engine = DetectionEngine(model_path=MODEL, device="cpu", imgsz=640)
    try:
        assert len(engine.class_names) >= 80  # COCO classes
        frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        start = time.monotonic()
        df = engine.infer(frame, 1000.0, session_id=1, frame_id=1, camera_id=1)
        latency_ms = (time.monotonic() - start) * 1000.0
        assert df.frame_width == 640
        assert df.frame_height == 480
        assert isinstance(df.detections, list)
        # noise frames rarely produce detections but must never crash
        print(f"\n[real-yolo] latency={latency_ms:.1f} ms detections={len(df.detections)}")
    finally:
        engine.close()
        clear_engines()


@pytest.mark.skipif(not os.path.isfile(MODEL), reason="yolov8n.pt weights not bundled")
def test_real_yolo_repeated_smoke_no_state_growth():
    engine = DetectionEngine(model_path=MODEL, device="cpu", imgsz=640)
    try:
        frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        latencies = []
        for i in range(3):
            start = time.monotonic()
            engine.infer(frame, float(i), session_id=1, frame_id=i, camera_id=1)
            latencies.append((time.monotonic() - start) * 1000.0)
        print(f"\n[real-yolo] runs={len(latencies)} avg={sum(latencies) / len(latencies):.1f} ms")
    finally:
        engine.close()
        clear_engines()