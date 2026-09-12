"""Phase 5 integration tests: forensic evidence wired into live sessions.

Covers: tracking event -> TRACK_EVENT evidence rows in PG + provenance + stored
bytes; VLM observation -> observation record + FRAME/VLM_OBSERVATION rows +
async vector indexing to INDEXED; evidence REST API (list / detail / content /
reindex) with RBAC; semantic search; live status evidence metrics.

No real camera, network, VLM provider, MinIO or Qdrant is involved; storage uses
the local fallback and Qdrant the deterministic in-memory fallback.
"""

import time

import numpy as np
import pytest

from app.core.config import settings
from app.live.manager import manager
import app.detection.pipeline as pipeline_mod
from detection_fakes import FakeEngine


def create_camera(client, headers, name="P5-CAM"):
    res = client.post(
        "/cameras",
        headers=headers,
        json={"camera_name": name, "location": "P5 scene", "camera_type": "MOBILE"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def wait_for(predicate, timeout=8.0, step=0.03):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


@pytest.fixture
def detected(monkeypatch):
    """Enable detection globally for these tests and share one fake engine."""
    shared = FakeEngine(detections_per_call=[1, 1, 1])
    monkeypatch.setattr(settings, "YOLO_DETECTION_ENABLED", True)
    monkeypatch.setattr(pipeline_mod, "get_engine", lambda *a, **k: shared)
    return shared


@pytest.fixture
def live_config(monkeypatch):
    """Fast, deterministic VLM + tiny evidence capture window for the pipeline."""
    monkeypatch.setattr(settings, "VLM_ENABLED", True)
    monkeypatch.setattr(settings, "VLM_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(settings, "VLM_MAX_REQUESTS_PER_SESSION", 200)
    monkeypatch.setattr(
        settings,
        "VLM_EVENT_TRIGGERS",
        "object_entered,object_stopped,object_reappeared,prolonged_presence,object_exited",
    )
    monkeypatch.setattr(settings, "VLM_RETRIES", 0)
    monkeypatch.setattr(settings, "VLM_RETRY_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr(settings, "VLM_MAX_FRAMES_PER_REQUEST", 3)
    monkeypatch.setattr(settings, "EVIDENCE_ENABLED", True)
    monkeypatch.setattr(settings, "EVIDENCE_MAX_FRAMES_PER_CAPTURE", 1)
    monkeypatch.setattr(settings, "EVIDENCE_MAX_IMAGE_SIDE", 320)
    monkeypatch.setattr(settings, "EVIDENCE_JPEG_QUALITY", 90)


def _np_frame(value=64):
    return np.full((240, 320, 3), value, dtype=np.uint8)


def _det_frame(frame_id, ts, n=1):
    from app.detection.schemas import BoundingBox, DetectionFrame, DetectionObject

    dets = [
        DetectionObject(
            detection_id=f"d-{frame_id}-{i}",
            class_id=0,
            class_name="person",
            confidence=0.9,
            bbox=BoundingBox(x1=10, y1=10 + i * 40, x2=110, y2=110 + i * 40),
            frame_timestamp=ts,
            session_id=7,
            frame_id=frame_id,
            camera_id=3,
            frame_width=320,
            frame_height=240,
        )
        for i in range(n)
    ]
    return DetectionFrame(
        session_id=7,
        camera_id=3,
        frame_id=frame_id,
        frame_timestamp=ts,
        frame_width=320,
        frame_height=240,
        detections=dets,
    )


def _start_sim(client, headers, cam_id, name):
    start = client.post(
        f"/live/cameras/{cam_id}/start", headers=headers, json={"transport": "simulation"}
    )
    assert start.status_code == 201, start.text
    runtime = manager.get(cam_id)
    runtime.simulation.stop()
    runtime.simulation = None
    return runtime


def _seed_buffer(runtime, n=5, t0=None, value=64):
    t0 = t0 if t0 is not None else time.time() - 2.0
    for i in range(n):
        runtime.buffer.append(_np_frame(value), t0 + i)
    return t0


def _trigger_object_entered(runtime, t0):
    for i in (1, 2, 3):
        runtime._on_detection_result(_det_frame(i, t0 + i))


def _fresh_db():
    from app.database.session import SessionLocal

    return SessionLocal()


# ------------------------------------------------------- capture on event


def test_tracking_event_captures_track_event_evidence(client, auth_headers, detected, live_config):
    from app.database.models import ForensicEvidence

    cam = create_camera(client, auth_headers, "P5-EVT")
    runtime = _start_sim(client, auth_headers, cam["id"], "P5-EVT")
    runtime.mark_live()
    assert runtime.evidence is not None
    assert runtime.evidence.enabled

    t0 = _seed_buffer(runtime)
    _trigger_object_entered(runtime, t0)

    db = _fresh_db()
    try:
        assert wait_for(
            lambda: db.query(ForensicEvidence)
            .filter(
                ForensicEvidence.session_id == runtime.session_db_id,
                ForensicEvidence.evidence_type == "TRACK_EVENT",
            )
            .count()
            > 0
        )
        row = (
            db.query(ForensicEvidence)
            .filter(
                ForensicEvidence.session_id == runtime.session_db_id,
                ForensicEvidence.evidence_type == "TRACK_EVENT",
            )
            .order_by(ForensicEvidence.id.desc())
            .first()
        )
        assert row.public_id.startswith("EVD-")
        assert row.event_type
        assert row.storage_path and row.sha256
        assert row.camera_id == cam["id"]
        assert row.session_id == runtime.session_db_id
        assert row.source == "DERIVED"
        assert row.index_status in ("PENDING", "INDEXING", "INDEXED")

        from app.storage.service import storage

        assert storage.exists(row.storage_path)
        content = storage.get_bytes(row.storage_path)
        assert content[:2] == b"\xff\xd8"  # JPEG magic
        assert row.size_bytes == len(content)
    finally:
        db.close()
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_evidence_available_in_status_snapshot(client, auth_headers, detected, live_config):
    cam = create_camera(client, auth_headers, "P5-STATUS")
    runtime = _start_sim(client, auth_headers, cam["id"], "P5-STATUS")
    runtime.mark_live()
    t0 = _seed_buffer(runtime)
    _trigger_object_entered(runtime, t0)

    assert wait_for(lambda: runtime.evidence_snapshot()["evidence_captured"] >= 1)
    snap = runtime.snapshot()
    assert snap["evidence_enabled"] is True
    assert snap["evidence_captured"] >= 1
    assert "evidence_indexed" in snap

    res = client.get(f"/live/cameras/{cam['id']}/status", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("evidence_enabled") is True
    assert body.get("evidence_captured", 0) >= 1
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_vlm_observation_persists_and_indexes(client, auth_headers, detected, live_config):
    from app.database.models import ForensicEvidence, VlmObservationRecord
    from app.storage.service import storage

    cam = create_camera(client, auth_headers, "P5-OBS")
    runtime = _start_sim(client, auth_headers, cam["id"], "P5-OBS")
    runtime.mark_live()
    t0 = _seed_buffer(runtime, value=80)
    _trigger_object_entered(runtime, t0)

    db = _fresh_db()
    try:
        # Observation persists regardless of indexing.
        assert wait_for(
            lambda: db.query(VlmObservationRecord)
            .filter(VlmObservationRecord.session_id == runtime.session_db_id)
            .count()
            > 0
        )
        rec = (
            db.query(VlmObservationRecord)
            .filter(VlmObservationRecord.session_id == runtime.session_db_id)
            .order_by(VlmObservationRecord.id.desc())
            .first()
        )
        assert rec.observation_id
        assert rec.summary.strip()

        # Evidence rows reference the observation and hold groundable content.
        assert wait_for(
            lambda: (
                db.query(ForensicEvidence)
                .filter(ForensicEvidence.session_id == runtime.session_db_id)
                .filter(ForensicEvidence.evidence_type == "VLM_OBSERVATION")
                .count()
            )
            > 0
        )
        assert wait_for(
            lambda: (
                db.query(ForensicEvidence)
                .filter(ForensicEvidence.session_id == runtime.session_db_id)
                .filter(ForensicEvidence.evidence_type == "FRAME")
                .count()
            )
            > 0
        )
        ev_rows = (
            db.query(ForensicEvidence)
            .filter(ForensicEvidence.session_id == runtime.session_db_id)
            .all()
        )
        types = {r.evidence_type for r in ev_rows}
        assert "VLM_OBSERVATION" in types
        obs_rows = [r for r in ev_rows if r.vlm_observation_id == rec.observation_id]
        assert obs_rows
        assert any(r.storage_path and storage.exists(r.storage_path) for r in obs_rows)

        # Async indexing completes to INDEXED.
        try:
            rec_id = rec.observation_id
            assert wait_for(
                lambda: db.query(ForensicEvidence)
                .filter(
                    ForensicEvidence.session_id == runtime.session_db_id,
                    ForensicEvidence.vlm_observation_id == rec_id,
                    ForensicEvidence.index_status == "INDEXED",
                )
                .count()
                > 0
            )
        finally:
            rec_id = None
    finally:
        db.close()
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_evidence_dedup_across_observations(client, auth_headers, detected, live_config):
    from app.database.models import ForensicEvidence

    cam = create_camera(client, auth_headers, "P5-DEDUP")
    runtime = _start_sim(client, auth_headers, cam["id"], "P5-DEDUP")
    runtime.mark_live()
    # Seed EXACT same frame bytes twice around two triggered events.
    t0 = time.time() - 1.0
    runtime.buffer.append(_np_frame(200), t0)
    _trigger_object_entered(runtime, t0)
    time.sleep(0.4)
    runtime.buffer.append(_np_frame(200), time.time())
    _trigger_object_entered(runtime, time.time())

    db = _fresh_db()
    try:
        assert wait_for(
            lambda: db.query(ForensicEvidence)
            .filter(
                ForensicEvidence.session_id == runtime.session_db_id,
                ForensicEvidence.evidence_type == "TRACK_EVENT",
            )
            .count()
            > 0
        )
        rows = (
            db.query(ForensicEvidence)
            .filter(ForensicEvidence.session_id == runtime.session_db_id)
            .all()
        )
        # identical bytes on one session must never be stored twice: for each
        # sha256 present, exactly one object path may exist.
        by_sha = {}
        for r in rows:
            if not r.storage_path:
                continue
            by_sha.setdefault(r.sha256, set()).add(r.storage_path)
        assert by_sha, "no stored evidence captured"
        for sha, paths in by_sha.items():
            assert len(paths) == 1, f"duplicate objects for sha {sha}: {paths}"
    finally:
        db.close()
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


# ------------------------------------------------------- evidence REST API


def test_evidence_api_list_detail_content(client, auth_headers, detected, live_config):
    from app.database.models import ForensicEvidence

    cam = create_camera(client, auth_headers, "P5-API")
    runtime = _start_sim(client, auth_headers, cam["id"], "P5-API")
    runtime.mark_live()
    t0 = _seed_buffer(runtime)
    _trigger_object_entered(runtime, t0)

    db = _fresh_db()
    try:
        assert wait_for(
            lambda: db.query(ForensicEvidence)
            .filter(ForensicEvidence.session_id == runtime.session_db_id)
            .count()
            > 0
        )
        row = (
            db.query(ForensicEvidence)
            .filter(
                ForensicEvidence.session_id == runtime.session_db_id,
                ForensicEvidence.storage_path.isnot(None),
            )
            .order_by(ForensicEvidence.id.desc())
            .first()
        )
    finally:
        db.close()
    assert row is not None

    res = client.get("/evidence/live", headers=auth_headers)
    assert res.status_code == 200, res.text
    listing = res.json()
    assert any(item["public_id"] == row.public_id for item in listing)

    res = client.get(f"/evidence/live?session_id={runtime.session_db_id}", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert any(item["public_id"] == row.public_id for item in res.json())

    res = client.get(f"/evidence/live/{row.public_id}", headers=auth_headers)
    assert res.status_code == 200, res.text
    detail = res.json()
    assert detail["provenance"]["generated_by"] == "server"
    assert detail["provenance"]["evidence_id"] == row.public_id
    assert "metadata" in detail

    res = client.get(f"/evidence/live/{row.public_id}/content", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("image/jpeg")
    assert res.headers.get("x-evidence-sha256") == row.sha256
    assert res.content[:2] == b"\xff\xd8"
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_evidence_api_rbac(client, auth_headers, reviewer_headers, detected, live_config):
    cam = create_camera(client, auth_headers, "P5-RBAC")
    runtime = _start_sim(client, auth_headers, cam["id"], "P5-RBAC")
    runtime.mark_live()

    # Reviewer (no live role) must be denied.
    res = client.get("/evidence/live", headers=reviewer_headers)
    assert res.status_code in (401, 403)
    # Unauthenticated must be denied.
    res = client.get("/evidence/live")
    assert res.status_code in (401, 403)

    res = client.post("/live/cameras/99999/vlm/analyze", headers=auth_headers, json={"trigger": "manual"})
    # 99999 never starts a session; stop cleanly
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)
    assert res.status_code == 404


def test_evidence_api_404_for_unknown(client, auth_headers, detected, live_config):
    res = client.get("/evidence/live/EVD-NOPE", headers=auth_headers)
    assert res.status_code == 404
    res = client.post("/evidence/live/EVD-NOPE/reindex", headers=auth_headers)
    assert res.status_code == 404


def test_evidence_reindex_api(client, auth_headers, detected, live_config):
    from app.database.models import ForensicEvidence

    cam = create_camera(client, auth_headers, "P5-REIDX")
    runtime = _start_sim(client, auth_headers, cam["id"], "P5-REIDX")
    runtime.mark_live()
    t0 = _seed_buffer(runtime)
    _trigger_object_entered(runtime, t0)

    db = _fresh_db()
    try:
        assert wait_for(
            lambda: (db.query(ForensicEvidence)
                     .filter(ForensicEvidence.session_id == runtime.session_db_id)
                     .count()) > 0
        )
        row = (
            db.query(ForensicEvidence)
            .filter(ForensicEvidence.session_id == runtime.session_db_id)
            .order_by(ForensicEvidence.id.desc())
            .first()
        )
        ev_id = row.id
        ev_public_id = row.public_id
        row.index_status = "FAILED"
        row.index_error = "forced for test"
        db.commit()
    finally:
        db.close()

    res = client.post(f"/evidence/live/{ev_public_id}/reindex", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reindexed"] is True

    from app.database.session import SessionLocal
    import sqlalchemy as sa

    db2 = SessionLocal()
    try:
        assert wait_for(
            lambda: (
                db2.execute(
                    sa.select(ForensicEvidence.index_status).where(
                        ForensicEvidence.id == int(ev_id)
                    )
                ).scalar()
                == "INDEXED"
            )
        )
        final_row = db2.execute(
            sa.select(ForensicEvidence).where(ForensicEvidence.id == int(ev_id))
        ).scalar_one()
        assert final_row.indexed_at is not None
    finally:
        db2.close()
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def test_evidence_search_api(client, auth_headers, detected, live_config):
    from app.database.models import ForensicEvidence

    cam = create_camera(client, auth_headers, "P5-SEARCH")
    runtime = _start_sim(client, auth_headers, cam["id"], "P5-SEARCH")
    runtime.mark_live()
    t0 = _seed_buffer(runtime, value=90)
    _trigger_object_entered(runtime, t0)

    db = _fresh_db()
    try:
        assert wait_for(
            lambda: (db.query(ForensicEvidence)
                     .filter(ForensicEvidence.session_id == runtime.session_db_id)
                     .count()) > 0
        )
        assert wait_for(
            lambda: (db.query(ForensicEvidence)
                     .filter(
                         ForensicEvidence.session_id == runtime.session_db_id,
                         ForensicEvidence.index_status == "INDEXED",
                     )
                     .count()) > 1
        )
    finally:
        db.close()

    res = client.post("/evidence/live/search", headers=auth_headers, json={"query": "standing person"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] > 0
    known_ids = {
        r.public_id
        for r in SessionList(runtime.session_db_id)
    }
    assert any(item["evidence_id"] in known_ids for item in body["results"])

    # empty query rejected
    res = client.post("/evidence/live/search", headers=auth_headers, json={"query": ""})
    assert res.status_code == 422
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)


def SessionList(session_id):
    from app.database.models import ForensicEvidence
    from app.database.session import SessionLocal

    s = SessionLocal()
    try:
        return s.query(ForensicEvidence).filter(ForensicEvidence.session_id == session_id).all()
    finally:
        s.close()


# ------------------------------------------------------- disable-by-config


def test_evidence_disabled_by_config(client, auth_headers, detected, live_config, monkeypatch):
    monkeypatch.setattr(settings, "EVIDENCE_ENABLED", False)
    cam = create_camera(client, auth_headers, "P5-DISABLE")
    runtime = _start_sim(client, auth_headers, cam["id"], "P5-DISABLE")
    runtime.mark_live()
    assert runtime.evidence is None
    assert runtime.evidence_error is not None
    snap = runtime.snapshot()
    assert snap["evidence_enabled"] is False
    client.post(f"/live/cameras/{cam['id']}/stop", headers=auth_headers)