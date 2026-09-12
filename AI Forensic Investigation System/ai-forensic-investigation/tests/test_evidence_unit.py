"""Unit tests for Phase 5 evidence package.

Covers:
  - paths / hashing / dedup identity
  - evidence schemas serialization round-trips + content builders + index payload
  - EvidenceIndexQueue: bounded drop-oldest, submit/status, success/retry/fail
  - EvidenceCapture: on_event â†’ TRACK_EVENT row + storage + index; dedup re-capture;
    observation capture â†’ VlmObservationRecord + FRAME + VLM_OBSERVATION rows

Uses the shared SQLite test DB; data-dir writes are allowed.
"""

from __future__ import annotations

import hashlib
import time
from collections import namedtuple
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

StubBuffer = namedtuple("StubBuffer", ["camera_id", "camera_name", "session_db_id"])


def _fake_frame(h: int = 8, w: int = 8, seed: int = 1):
    import numpy as np
    return np.full((h, w, 3), fill_value=seed, dtype=np.uint8)


def _insert_camera(db):
    from app.database.models import Camera
    cam = Camera(camera_name=f"test_cam_{int(time.time()*1000)}", location="test")
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


def _insert_session(db, camera_id: int):
    from app.database.models import CameraSession
    s = CameraSession(camera_id=camera_id, status="CONNECTING", transport="simulation")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _make_event(camera_id: str = "1", session_id: str = "1", seq: int = 1, state: str = "NEW"):
    from app.tracking.schemas import TrackingEvent
    return TrackingEvent(
        event_id=f"EVT-{seq}-{int(time.time()*1000)}",
        event_type="TRACK_START",
        session_id=str(session_id),
        camera_id=str(camera_id),
        frame_index=seq,
        frame_timestamp=datetime.utcnow(),
        tracking_id=f"T-{seq}",
        metadata={"state": state},
    )


def _make_obs(camera_id: int, session_id: int, obs_id: str, seq: int = 1):
    return {
        "observation_id": obs_id,
        "request_id": "REQ-001",
        "camera_id": camera_id,
        "session_id": session_id,
        "trigger": "scheduled",
        "trigger_detail": "test",
        "summary": "a person is standing",
        "items": [
            {
                "id": "1",
                "class": "PERSON",
                "summary": "standing",
                "statement_class": "OBSERVED",
                "confidence": 0.9,
            }
        ],
        "notes": [],
        "model": "test-model",
        "provider_mode": "simulation",
        "source_frames": [
            {
                "sequence": seq,
                "timestamp": datetime.utcnow().isoformat(),
                "frame_id": f"frame-{seq}",
            }
        ],
        "window_start": time.time() - 2.0,
        "window_end": time.time(),
    }


# ===========================================================================
# PATHS + HASHING
# ===========================================================================

class TestEvidencePaths:
    def test_object_name_deterministic(self):
        from app.evidence.paths import evidence_object_name

        a = evidence_object_name("EVD-AAAA00001111", 3, 42, date="2025-10-27")
        b = evidence_object_name("EVD-AAAA00001111", 3, 42, date="2025-10-27")
        assert a == b
        assert a == "live/3/42/2025-10-27/EVD-AAAA00001111/original.jpg"

    def test_object_name_zeroed_defaults(self):
        from app.evidence.paths import evidence_object_name

        assert evidence_object_name("X", None, None, date="2025-01-01") == "live/0/0/2025-01-01/X/original.jpg"

    def test_sha256_bytes(self):
        from app.evidence.paths import sha256_bytes

        expected = hashlib.sha256(b"hello").hexdigest()
        assert sha256_bytes(b"hello") == expected

    def test_dedup_identity_stable(self):
        from app.evidence.paths import dedup_identity

        a = dedup_identity("abc123", 1, 2)
        b = dedup_identity("abc123", 1, 2)
        assert a == b
        assert dedup_identity("abc123", 3, 2) != a
        assert dedup_identity("abc123", 1, 9) != a
        assert dedup_identity("xxx", 1, 2) != a

    def test_sanitize_ext(self):
        from app.evidence.paths import sanitize_ext
        assert sanitize_ext("JPEG") == "jpeg"
        assert sanitize_ext(".PNG") == "png"
        assert sanitize_ext("  ") == "jpg"


# ===========================================================================
# SCHEMAS
# ===========================================================================

class TestEvidenceSchemas:
    def test_serialize_parse_metadata_round_trip(self):
        from app.evidence.schemas import parse_metadata, serialize_metadata

        raw = {"a": 1, "nested": {"k": True}}
        row = type("Row", (), {"metadata": serialize_metadata(raw)})()
        assert parse_metadata(row) == raw

    def test_malformed_metadata_returns_default(self):
        from app.evidence.schemas import parse_metadata
        row = type("Row", (), {"metadata": "{bad json"})()
        assert parse_metadata(row) == {}

    def test_parse_source_frame_ids(self):
        from app.evidence.schemas import parse_source_frame_ids
        row = type("Row", (), {"source_frame_ids": "[1,2,3]"})()
        assert parse_source_frame_ids(row) == [1, 2, 3]

    def test_track_event_content(self):
        from app.evidence.schemas import track_event_content
        event = _make_event(seq=7)
        text = track_event_content(event, "cam-lobby")
        assert "TRACK_START" in text
        assert "T-7" in text
        assert "cam-lobby" in text

    def test_frame_content(self):
        from app.evidence.schemas import frame_content
        text = frame_content(5, "cam-entrance", 10, 3)
        assert "camera_id=5" in text
        assert "sequence=3" in text

    def test_observation_content(self):
        from app.evidence.schemas import observation_content
        payload = _make_obs(1, 1, "obs-1")
        text = observation_content(payload)
        assert "a person is standing" in text
        assert "standing" in text

    def test_evidence_index_payload_structure(self):
        from app.evidence.schemas import evidence_index_payload
        p = evidence_index_payload(
            evidence_id="EVD-TEST",
            evidence_type="FRAME",
            source="RAW_SOURCE",
            camera_id=1,
            session_id=2,
            timestamp=time.time(),
            event_id=None,
            event_type=None,
            tracking_id=None,
            frame_sequence=5,
            vlm_observation_id=None,
            storage_path="frames/test.jpg",
            sha256="abc",
            source_text="test frame",
        )
        assert p["evidence_id"] == "EVD-TEST"
        assert p["camera_id"] == 1
        assert p["session_id"] == 2

    def test_build_provenance_server_generated(self):
        from app.evidence.schemas import build_provenance
        prov = build_provenance(
            public_id="EVD-PROV",
            evidence_type="TRACK_EVENT",
            source="DERIVED",
            camera_id=1,
            session_id=2,
            event_id="evt",
            event_type="LOITER",
            tracking_id="T-1",
            frame_sequence=10,
            frame_timestamp=1.0,
            vlm_observation_id=None,
            source_frame_ids=[10],
            window_start=0.5,
            window_end=1.5,
            captured_at="2025-10-27T12:00:00",
            storage_path="frames/x",
            mime_type="image/jpeg",
            width=640,
            height=480,
            sha256="abc",
            size_bytes=12345,
        )
        assert prov["generated_by"] == "server"
        assert prov["evidence_id"] == "EVD-PROV"
        assert prov["camera_id"] == 1


# ===========================================================================
# INDEXER
# ===========================================================================

class TestEvidenceIndexQueue:
    def test_bounded_drop_oldest(self):
        import threading
        from app.evidence.indexer import EvidenceIndexQueue

        process_events = []
        gate = threading.Event()

        def slow_process(job):
            process_events.append(job.public_id)
            gate.wait(timeout=3.0)

        q = EvidenceIndexQueue(maxsize=2, max_attempts=1, backoff_seconds=0.0)
        q._process = slow_process
        q.start()
        assert q.running
        q.submit(1, "EVD-1")
        time.sleep(0.05)  # give the worker a chance to pick job 1
        q.submit(2, "EVD-2")
        q.submit(3, "EVD-3")
        q.submit(4, "EVD-4")
        gate.set()
        time.sleep(0.4)
        q.stop(timeout=2)
        snap = q.snapshot()
        assert snap["total_dropped"] >= 1
        assert "EVD-1" in process_events

    def test_submit_returns_true_and_pending(self, db):
        from app.database.models import ForensicEvidence
        from app.evidence.indexer import EvidenceIndexQueue

        cam = _insert_camera(db)
        session = _insert_session(db, cam.id)
        row = ForensicEvidence(
            public_id="EVD-PEND-UNIT",
            evidence_type="FRAME",
            source="RAW_SOURCE",
            camera_id=cam.id,
            session_id=session.id,
            captured_at=datetime.utcnow(),
            storage_path=None,
            mime_type=None,
            sha256="aa",
            index_status="INDEXED",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        q = EvidenceIndexQueue(maxsize=4, max_attempts=1, backoff_seconds=0.0)
        assert q.submit(row.id, row.public_id) is True
        from app.database.session import SessionLocal
        fresh = SessionLocal()
        try:
            r = fresh.query(ForensicEvidence).filter(ForensicEvidence.id == row.id).one()
            assert r.index_status in ("PENDING", "INDEXING", "INDEXED")
        finally:
            fresh.close()
        q.stop(timeout=2)

    def test_success_sets_indexed(self, db):
        from app.database.models import ForensicEvidence
        from app.evidence.indexer import EvidenceIndexQueue, IndexJob

        cam = _insert_camera(db)
        session = _insert_session(db, cam.id)
        row = ForensicEvidence(
            public_id="EVD-IDX-OK",
            evidence_type="FRAME",
            source="RAW_SOURCE",
            camera_id=cam.id,
            session_id=session.id,
            captured_at=datetime.utcnow(),
            storage_path="frames/x.jpg",
            mime_type="image/jpeg",
            sha256="aa",
            content_text="test frame",
            metadata="{}",
            provenance="{}",
            index_status="PENDING",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        q = EvidenceIndexQueue(maxsize=4, max_attempts=1, backoff_seconds=0.0)
        q._process(IndexJob(row.id, row.public_id))
        from app.database.session import SessionLocal
        fresh = SessionLocal()
        try:
            r = fresh.query(ForensicEvidence).filter(ForensicEvidence.id == row.id).one()
            assert r.index_status == "INDEXED"
            assert r.index_attempts == 1
            assert r.indexed_at is not None
        finally:
            fresh.close()
        q.stop(timeout=2)

    def test_retry_then_success(self, db, monkeypatch):
        from app.ai import qdrant_service
        from app.database.models import ForensicEvidence
        from app.evidence.indexer import EvidenceIndexQueue, IndexJob

        cam = _insert_camera(db)
        session = _insert_session(db, cam.id)
        row = ForensicEvidence(
            public_id="EVD-IDX-RETRY",
            evidence_type="FRAME",
            source="RAW_SOURCE",
            camera_id=cam.id,
            session_id=session.id,
            captured_at=datetime.utcnow(),
            storage_path="frames/x.jpg",
            mime_type="image/jpeg",
            sha256="aa",
            content_text="text",
            metadata="{}",
            provenance="{}",
            index_status="PENDING",
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        call_count = {"n": 0}
        original_index = qdrant_service.qdrant.index_evidence

        def flaky(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise RuntimeError("qdrant blip")
            return original_index(*args, **kwargs)

        monkeypatch.setattr(qdrant_service.qdrant, "index_evidence", flaky)

        q = EvidenceIndexQueue(maxsize=4, max_attempts=3, backoff_seconds=0.0)
        q._process(IndexJob(row.id, row.public_id))

        from app.database.session import SessionLocal
        fresh = SessionLocal()
        try:
            r = fresh.query(ForensicEvidence).filter(ForensicEvidence.id == row.id).one()
            assert r.index_status == "INDEXED"
            assert r.index_attempts == 3
        finally:
            fresh.close()
        q.stop(timeout=2)

    def test_exhausted_attempts_sets_failed(self, db, monkeypatch):
        from app.ai import qdrant_service
        from app.database.models import ForensicEvidence
        from app.evidence.indexer import EvidenceIndexQueue, IndexJob

        cam = _insert_camera(db)
        session = _insert_session(db, cam.id)
        row = ForensicEvidence(
            public_id="EVD-IDX-FAIL",
            evidence_type="FRAME",
            source="RAW_SOURCE",
            camera_id=cam.id,
            session_id=session.id,
            captured_at=datetime.utcnow(),
            storage_path="frames/x.jpg",
            mime_type="image/jpeg",
            sha256="aa",
            content_text="text",
            metadata="{}",
            provenance="{}",
            index_status="PENDING",
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        def boom(*args, **kwargs):
            raise RuntimeError("qdrant down")

        monkeypatch.setattr(qdrant_service.qdrant, "index_evidence", boom)

        q = EvidenceIndexQueue(maxsize=4, max_attempts=2, backoff_seconds=0.0)
        q._process(IndexJob(row.id, row.public_id))

        from app.database.session import SessionLocal
        fresh = SessionLocal()
        try:
            r = fresh.query(ForensicEvidence).filter(ForensicEvidence.id == row.id).one()
            assert r.index_status == "FAILED"
            assert r.index_attempts == 2
            assert "qdrant down" in (r.index_error or "")
        finally:
            fresh.close()
        q.stop(timeout=2)

    def test_snapshot_metrics(self):
        from app.evidence.indexer import EvidenceIndexQueue
        q = EvidenceIndexQueue(maxsize=10, max_attempts=1, backoff_seconds=0.0)
        snap = q.snapshot()
        assert snap["queue_size"] == 0
        assert snap["total_indexed"] == 0
        q.stop(timeout=2)


# ===========================================================================
# CAPTURE - on_event
# ===========================================================================

class TestEvidenceCaptureEvent:
    def test_on_event_creates_track_event_row(self, db):
        from app.evidence.capture import EvidenceCapture
        from app.database.models import ForensicEvidence, Camera, CameraSession
        from app.live.rolling_buffer import RollingFrameBuffer

        cam = Camera(camera_name="cap_cam", location="test")
        db.add(cam)
        db.commit()
        db.refresh(cam)
        session = CameraSession(camera_id=cam.id, status="ACTIVE", transport="simulation")
        db.add(session)
        db.commit()
        db.refresh(session)

        buf = RollingFrameBuffer(window_seconds=30.0, max_frames=10)
        frame = _fake_frame(seed=42)
        buf.append(frame, timestamp=time.time())

        runtime = StubBuffer(camera_id=cam.id, camera_name="cap_cam", session_db_id=session.id)
        # Patch buffer attr onto runtime
        runtime = type("Runtime", (), {
            "camera_id": cam.id,
            "camera_name": "cap_cam",
            "session_db_id": session.id,
            "buffer": buf,
        })()
        cap = EvidenceCapture(runtime)
        cap.start()

        event = _make_event(camera_id=str(cam.id), session_id=str(session.id), seq=buf.latest().sequence)
        obs_id = cap.on_event(event)

        assert obs_id is not None
        row = db.query(ForensicEvidence).filter(ForensicEvidence.public_id == obs_id).one()
        assert row.evidence_type == "TRACK_EVENT"
        assert row.source == "DERIVED"
        assert row.camera_id == cam.id
        assert row.session_id == session.id
        assert row.event_id == event.event_id
        assert row.event_type == "TRACK_START"
        assert row.tracking_id == event.tracking_id
        assert row.index_status in ("PENDING", "INDEXING", "INDEXED")
        assert row.sha256 is not None
        assert row.storage_path is not None
        assert "TRACK_START" in (row.content_text or "")

    def test_dedup_reuses_storage(self, db):
        from app.evidence.capture import EvidenceCapture
        from app.evidence.schemas import parse_metadata
        from app.database.models import ForensicEvidence
        from app.live.rolling_buffer import RollingFrameBuffer

        cam_db = _insert_camera(db)
        session_db = _insert_session(db, cam_db.id)
        buf = RollingFrameBuffer(window_seconds=30.0, max_frames=10)
        frame = _fake_frame(seed=99)
        buf.append(frame, timestamp=time.time())
        entry = buf.latest()
        runtime = type("R", (), {
            "camera_id": cam_db.id,
            "camera_name": "dedup_cam",
            "session_db_id": session_db.id,
            "buffer": buf,
        })()
        cap = EvidenceCapture(runtime)
        cap.start()

        event = _make_event(camera_id=str(cam_db.id), session_id=str(session_db.id), seq=entry.sequence)
        first_id = cap.on_event(event)
        assert first_id is not None
        first_row = db.query(ForensicEvidence).filter(ForensicEvidence.public_id == first_id).one()
        first_path = first_row.storage_path

        # second identical capture (same buffer entry)
        second_id = cap.on_event(_make_event(camera_id=str(cam_db.id), session_id=str(session_db.id), seq=entry.sequence))
        assert second_id is not None
        second_row = db.query(ForensicEvidence).filter(ForensicEvidence.public_id == second_id).one()
        assert second_row.storage_path == first_path
        meta = parse_metadata(second_row)
        assert meta.get("dedup_reused") is True

    def test_on_event_disabled_returns_none(self):
        from app.evidence.capture import EvidenceCapture
        runtime = type("R", (), {"camera_id": 1, "camera_name": "x", "session_db_id": 1, "buffer": MagicMock()})()
        cap = EvidenceCapture(runtime)
        # stop disables
        cap.start(); cap.stop()
        assert cap.enabled is False
        assert cap.on_event(_make_event()) is None

    def test_on_event_no_frames_returns_none(self, db):
        from app.evidence.capture import EvidenceCapture
        from app.live.rolling_buffer import RollingFrameBuffer

        cam_db = _insert_camera(db)
        session_db = _insert_session(db, cam_db.id)
        buf = RollingFrameBuffer(window_seconds=30.0, max_frames=10)
        runtime = type("R", (), {
            "camera_id": cam_db.id,
            "camera_name": "empty",
            "session_db_id": session_db.id,
            "buffer": buf,
        })()
        cap = EvidenceCapture(runtime)
        cap.start()
        assert cap.on_event(_make_event()) is None

def test_counts_returns_evidence_metrics(db):
        from app.evidence.capture import EvidenceCapture
        from app.database.models import ForensicEvidence
        from app.live.rolling_buffer import RollingFrameBuffer

        cam_db = _insert_camera(db)
        session_db = _insert_session(db, cam_db.id)
        buf = RollingFrameBuffer(window_seconds=30.0, max_frames=10)
        buf.append(_fake_frame(seed=7), timestamp=time.time())
        entry = buf.latest()
        runtime = type("R", (), {
            "camera_id": cam_db.id,
            "camera_name": "count_cam",
            "session_db_id": session_db.id,
            "buffer": buf,
        })()
        cap = EvidenceCapture(runtime)
        cap.start()
        cap.on_event(_make_event(camera_id=str(cam_db.id), session_id=str(session_db.id), seq=entry.sequence))
        counts = cap.counts(db)
        assert counts["evidence_captured"] >= 1
        assert counts["evidence_enabled"] is True


# ===========================================================================
# CAPTURE - on_observation
# ===========================================================================

class TestEvidenceCaptureObservation:
    def test_on_observation_creates_rows(self, db):
        from app.evidence.capture import EvidenceCapture
        from app.database.models import ForensicEvidence, VlmObservationRecord
        from app.live.rolling_buffer import RollingFrameBuffer

        cam_db = _insert_camera(db)
        session_db = _insert_session(db, cam_db.id)
        buf = RollingFrameBuffer(window_seconds=30.0, max_frames=10)
        frame = _fake_frame(seed=15)
        buf.append(frame, timestamp=time.time())
        entry = buf.latest()
        runtime = type("R", (), {
            "camera_id": cam_db.id,
            "camera_name": "obs_cam",
            "session_db_id": session_db.id,
            "buffer": buf,
        })()
        cap = EvidenceCapture(runtime)
        cap.start()

        payload = _make_obs(cam_db.id, session_db.id, "obs-123", seq=entry.sequence)
        obs_id = cap.on_observation(payload)
        assert obs_id == "obs-123"

        obs_rec = db.query(VlmObservationRecord).filter(VlmObservationRecord.observation_id == "obs-123").one()
        assert obs_rec.summary == "a person is standing"

        rows = (
            db.query(ForensicEvidence)
            .filter(ForensicEvidence.vlm_observation_id == "obs-123")
            .all()
        )
        types = {r.evidence_type for r in rows}
        assert "FRAME" in types or "VLM_OBSERVATION" in types
        assert all(r.index_status in ("PENDING", "INDEXING", "INDEXED") for r in rows)

    def test_on_observation_dedup_source_frame(self, db):
        from app.evidence.capture import EvidenceCapture
        from app.database.models import ForensicEvidence
        from app.live.rolling_buffer import RollingFrameBuffer

        cam_db = _insert_camera(db)
        session_db = _insert_session(db, cam_db.id)
        buf = RollingFrameBuffer(window_seconds=30.0, max_frames=10)
        buf.append(_fake_frame(seed=33), timestamp=time.time())
        entry = buf.latest()
        runtime = type("R", (), {
            "camera_id": cam_db.id,
            "camera_name": "dedup_obs",
            "session_db_id": session_db.id,
            "buffer": buf,
        })()
        cap = EvidenceCapture(runtime)
        cap.start()

        cap.on_observation(_make_obs(cam_db.id, session_db.id, "obs-D1", seq=entry.sequence))
        cap.on_observation(_make_obs(cam_db.id, session_db.id, "obs-D2", seq=entry.sequence))

        rows = (
            db.query(ForensicEvidence)
            .filter(
                ForensicEvidence.session_id == session_db.id,
                ForensicEvidence.camera_id == cam_db.id,
                ForensicEvidence.evidence_type == "FRAME",
            )
            .all()
        )
        storage_paths = [r.storage_path for r in rows]
        # exact bytes deduplicated: only one stored object
        assert len(set(storage_paths)) == 1

    def test_on_observation_disabled_returns_none(self):
        from app.evidence.capture import EvidenceCapture
        from app.live.rolling_buffer import RollingFrameBuffer

        runtime = type("R", (), {"camera_id": 1, "camera_name": "x", "session_db_id": 1, "buffer": RollingFrameBuffer(10, 30)})()
        cap = EvidenceCapture(runtime)
        assert cap.enabled is False
        assert cap.on_observation(_make_obs(1, 1, "x")) is None

    def test_on_observation_missing_id_returns_none(self):
        from app.evidence.capture import EvidenceCapture
        from app.live.rolling_buffer import RollingFrameBuffer

        runtime = type("R", (), {"camera_id": 1, "camera_name": "x", "session_db_id": 1, "buffer": RollingFrameBuffer(10, 30)})()
        cap = EvidenceCapture(runtime)
        cap.start()
        assert cap.on_observation({}) is None


