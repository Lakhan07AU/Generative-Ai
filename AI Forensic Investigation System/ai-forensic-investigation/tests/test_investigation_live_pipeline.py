"""Phase 6: object-class propagation through the REAL live pipeline.

No mocks for tracking/events/capture/indexing: simulated frames -> detection
results -> tracking (person + car tracks) -> event detector -> TRACK_EVENT
evidence capture -> async vector indexing -> /investigation/search. Verifies
the label survives the whole chain and lands in the Qdrant payload as
``object_class``, including the "actual track id from the pipeline" track query.
"""

import time

import numpy as np
import pytest

from app.core.config import settings
from app.evidence.schemas import parse_metadata
from app.live.manager import manager
from tests.investigation_testdata import make_video_and_investigation, user_id_by_email


def wait_for(predicate, timeout=8.0, step=0.03):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


@pytest.fixture
def live_fast(monkeypatch):
    monkeypatch.setattr(settings, "VLM_ENABLED", False)
    monkeypatch.setattr(settings, "EVIDENCE_ENABLED", True)
    monkeypatch.setattr(settings, "EVIDENCE_MAX_FRAMES_PER_CAPTURE", 1)
    monkeypatch.setattr(settings, "EVIDENCE_MAX_IMAGE_SIDE", 320)
    monkeypatch.setattr(settings, "EVIDENCE_JPEG_QUALITY", 90)
    # Enable detection so mark_live() wires tracking + evidence, sharing a real
    # FakeEngine that returns no detections (the test feeds results manually).
    import app.detection.pipeline as pipeline_mod

    from detection_fakes import FakeEngine

    monkeypatch.setattr(settings, "YOLO_DETECTION_ENABLED", True)
    monkeypatch.setattr(pipeline_mod, "get_engine", lambda *a, **k: FakeEngine())
    monkeypatch.setattr(settings, "DETECTION_RECENT_FRAMES", 20)


def _np_frame(value=64):
    return np.full((240, 320, 3), value, dtype=np.uint8)


def _det_frame(person=True, car=True):
    from app.detection.schemas import BoundingBox, DetectionFrame, DetectionObject

    now = time.time()
    dets = []
    if person:
        dets.append(
            DetectionObject(
                detection_id="d-p", class_id=0, class_name="person", confidence=0.9,
                bbox=BoundingBox(x1=10, y1=10, x2=110, y2=110),
                frame_timestamp=now, session_id=7, frame_id=11, camera_id=3,
                frame_width=320, frame_height=240,
            )
        )
    if car:
        dets.append(
            DetectionObject(
                detection_id="d-c", class_id=1, class_name="car", confidence=0.9,
                bbox=BoundingBox(x1=120, y1=10, x2=220, y2=110),
                frame_timestamp=now, session_id=7, frame_id=11, camera_id=3,
                frame_width=320, frame_height=240,
            )
        )
    return DetectionFrame(
        session_id=7, camera_id=3, frame_id=11, frame_timestamp=now,
        frame_width=320, frame_height=240, detections=dets,
    )


def _fresh_db():
    from app.database.session import SessionLocal

    return SessionLocal()


def test_live_pipeline_object_class_reaches_search(client, auth_headers, live_fast):
    from app.database.models import ForensicEvidence

    res = client.post(
        "/cameras",
        headers=auth_headers,
        json={"camera_name": "P6-LIVE", "location": "pipeline scene", "camera_type": "CCTV"},
    )
    assert res.status_code == 201, res.text
    cam_id = res.json()["id"]

    start = client.post(
        f"/live/cameras/{cam_id}/start", headers=auth_headers, json={"transport": "simulation"}
    )
    assert start.status_code == 201, start.text
    runtime = manager.get(cam_id)
    runtime.simulation.stop()
    runtime.simulation = None
    runtime.mark_live()
    assert runtime.evidence is not None and runtime.evidence.enabled

    t0 = time.time() - 2.0
    for i in range(3):
        runtime.buffer.append(_np_frame(70), t0 + i)
    runtime._on_detection_result(_det_frame())

    db = _fresh_db()
    try:
        assert wait_for(
            lambda: (db.query(ForensicEvidence)
                     .filter(
                         ForensicEvidence.camera_id == cam_id,
                         ForensicEvidence.evidence_type == "TRACK_EVENT",
                     )
                     .count()) >= 2
        )
        assert wait_for(
            lambda: (db.query(ForensicEvidence)
                     .filter(
                         ForensicEvidence.camera_id == cam_id,
                         ForensicEvidence.index_status == "INDEXED",
                     )
                     .count()) >= 2
        )
        rows = (
            db.query(ForensicEvidence)
            .filter(
                ForensicEvidence.camera_id == cam_id,
                ForensicEvidence.index_status == "INDEXED",
            )
            .all()
        )
        labels = {}
        for r in rows:
            meta = parse_metadata(r)
            labels.setdefault(str(meta.get("label")), []).append(r)
    finally:
        db.close()

    assert labels.get("person"), "no person-labeled evidence captured"
    assert labels.get("car"), "no car-labeled evidence captured"
    car_row = labels["car"][0]
    track_id = car_row.tracking_id

    # Bind the case to this camera and search end-to-end.
    db2 = _fresh_db()
    inv = None
    try:
        uid = user_id_by_email(db2, "investigator@test.com")
        inv = make_video_and_investigation(db2, cam_id, uid)
    finally:
        db2.close()

    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": "Which cars entered the area?", "case_id": inv.id},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ANSWERED", body["answer"]
    assert body["results"]
    assert all(r["object_class"] == "car" for r in body["results"])

    # Track query must use the real track id produced by the pipeline.
    assert track_id
    res = client.post(
        "/investigation/search",
        headers=auth_headers,
        json={"query": f"Find all evidence for track {track_id}", "case_id": inv.id},
    )
    body = res.json()
    from app.investigation.query_parser import parse_query

    _p = parse_query(f"Find all evidence for track {track_id}")
    assert body["status"] == "ANSWERED", (
        f"track={track_id!r} parsed={_p.tracking_id!r} camera_scope={body['sources'].get('camera_ids')} "
        f"cams={body['sources'].get('camera_names')} reason={body['analysis'].get('reason')} body={body['answer']!r}"
    )
    assert body["results"]
    assert all(r["tracking_id"] == track_id for r in body["results"])

    client.post(f"/live/cameras/{cam_id}/stop", headers=auth_headers)