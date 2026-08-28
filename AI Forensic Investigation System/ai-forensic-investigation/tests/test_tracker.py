from app.vision.tracker import IoUTracker, iou


def test_iou_calculation():
    a = [0, 0, 10, 10]
    b = [0, 0, 10, 10]
    assert iou(a, b) == pytest_approx(1.0)

    # Non-overlapping boxes have zero IoU
    c = [20, 20, 30, 30]
    assert iou(a, c) == 0.0

    # Partially overlapping
    d = [5, 5, 15, 15]
    val = iou(a, d)
    assert 0.0 < val < 1.0


def pytest_approx(v):
    import pytest

    return pytest.approx(v)


def test_tracker_assigns_persistent_ids():
    tracker = IoUTracker()
    dets1 = [{"label": "person", "bbox": [0, 0, 20, 40], "confidence": 0.9}]
    r1 = tracker.update(dets1, 0)
    tid1 = r1[0]["tracking_id"]
    assert tid1.startswith("person-")

    # Small movement should keep the same track
    dets2 = [{"label": "person", "bbox": [2, 1, 21, 40], "confidence": 0.9}]
    r2 = tracker.update(dets2, 1)
    assert r2[0]["tracking_id"] == tid1


def test_tracker_new_id_for_new_object():
    tracker = IoUTracker()
    dets = [
        {"label": "person", "bbox": [0, 0, 20, 40], "confidence": 0.9},
        {"label": "person", "bbox": [100, 100, 120, 140], "confidence": 0.8},
    ]
    r1 = tracker.update(dets, 0)
    ids = {d["tracking_id"] for d in r1}
    assert len(ids) == 2


def test_tracker_drops_stale_tracks():
    tracker = IoUTracker(max_missing=2)
    dets1 = [{"label": "person", "bbox": [0, 0, 20, 40], "confidence": 0.9}]
    r1 = tracker.update(dets1, 0)
    tid = r1[0]["tracking_id"]

    # No detections for several frames -> track should eventually be dropped
    for _ in range(4):
        tracker.update([], 5)
    assert tid not in tracker.tracks
