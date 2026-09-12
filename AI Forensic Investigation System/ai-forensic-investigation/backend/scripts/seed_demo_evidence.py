"""Phase 6 demo evidence seeder.

In-process script against the configured PostgreSQL + Qdrant: creates (or reuses)
the DEMO-PHASE6 user / camera / video / investigation / session and inserts
deterministic DEMO forensic evidence bound to the case's camera - exactly the
rows + vector points the ``POST /investigation/search`` API reads. The record
layout mirrors the real Phase 5 capture path (stored JPEG object, sha256,
provenance, extra_metadata, content_text, INDEXED Qdrant point with
``object_class``).

Run from ``backend/``::

    python -m scripts.seed_demo_evidence
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from PIL import Image

from app.ai.embeddings import embeddings
from app.ai.qdrant_service import qdrant
from app.auth.security import hash_password
from app.database.models import (
    Camera,
    CameraSession,
    ForensicEvidence,
    Investigation,
    User,
    Video,
    VlmObservationRecord,
)
from app.database.session import SessionLocal
from app.evidence.paths import evidence_object_name, sha256_bytes
from app.evidence.schemas import (
    IndexStatus,
    build_provenance,
    evidence_index_payload,
    observation_content,
    serialize_metadata,
    serialize_provenance,
    track_event_content,
)
from app.storage.service import storage

DEMO_EMAIL = "demo.admin@forensics-demo.com"
DEMO_PASSWORD = "DemoAdmin123!"
DEMO_CAMERA = "DEMO-Phase6-Parking"
DEMO_CAMERA_LOCATION = "Parking area - vehicle entry"
DEMO_VIDEO = "phase6_demo_parking_10min.mp4"
DEMO_INVESTIGATION_TITLE = "CASE-DEMO-P6 Parking Area Vehicle Activity"
DEMO_INVESTIGATION_QUERY = (
    "Question the parking area footage for people, vehicles and track evidence "
    "between 10:00 and 10:15."
)

_BUCKET = "frames"
_EXT = ".jpg"
_MIME = "image/jpeg"
_WIDTH, _HEIGHT = 480, 270

# base session-relative epoch: 10:00:00
_T0 = 36000.0

# (timestamp, tracking_id, label, event_type, state)
_EVENTS: List[Dict[str, object]] = [
    {"ts": _T0 + 30, "tracking_id": "T-P6-PERSON-1", "label": "person", "event_type": "object_entered", "state": "entered"},
    {"ts": _T0 + 120, "tracking_id": "T-P6-PERSON-1", "label": "person", "event_type": "object_stopped", "state": "stopped"},
    {"ts": _T0 + 180, "tracking_id": "T-P6-PERSON-1", "label": "person", "event_type": "prolonged_presence", "state": "stationary"},
    {"ts": _T0 + 320, "tracking_id": "T-P6-PERSON-1", "label": "person", "event_type": "object_exited", "state": "exited"},
    {"ts": _T0 + 100, "tracking_id": "T-P6-CAR-2", "label": "car", "event_type": "object_entered", "state": "entered"},
    {"ts": _T0 + 300, "tracking_id": "T-P6-CAR-2", "label": "car", "event_type": "object_stopped", "state": "stopped"},
    {"ts": _T0 + 420, "tracking_id": "T-P6-CAR-2", "label": "car", "event_type": "object_moved", "state": "moving"},
    {"ts": _T0 + 450, "tracking_id": "T-P6-CAR-2", "label": "car", "event_type": "object_exited", "state": "exited"},
    {"ts": _T0 + 780, "tracking_id": "T-P6-CAR-3", "label": "car", "event_type": "object_entered", "state": "entered"},
    {"ts": _T0 + 900, "tracking_id": "T-P6-CAR-3", "label": "car", "event_type": "object_exited", "state": "exited"},
]

_OBSERVATION = {
    "observation_id": "VLM-DEMO-0001",
    "request_id": "REQ-DEMO-0001",
    "trigger": "event",
    "trigger_detail": "T-P6-CAR-2 object_entered",
    "summary": "A person is standing near the parking entrance while a car enters the parking area.",
    "items": [
        {"item_id": "it-1", "statement": "A person is standing near the parking entrance", "classification": "OBSERVED", "confidence": 0.92},
        {"item_id": "it-2", "statement": "A silver car is entering the parking area", "classification": "OBSERVED", "confidence": 0.9},
        {"item_id": "it-3", "statement": "The person may be waiting for the arriving car", "classification": "INFERRED", "confidence": 0.55},
        {"item_id": "it-4", "statement": "The person's identity cannot be determined from the footage", "classification": "UNKNOWN", "confidence": 0.1},
    ],
    "notes": ["DEMO seeded observation", "identity never inferred"],
    "model": "simulated-obs-demo",
    "provider_mode": "simulation",
    "source_frames": [
        {"frame_id": 1, "sequence": 18, "timestamp": _T0 + 30, "width": _WIDTH, "height": _HEIGHT},
        {"frame_id": 2, "sequence": 50, "timestamp": _T0 + 110, "width": _WIDTH, "height": _HEIGHT},
    ],
    "window_start": _T0 + 20,
    "window_end": _T0 + 140,
}

_COLORS = {
    "person": (232, 170, 60),
    "car": (70, 130, 200),
    "observation": (60, 170, 130),
}


def _make_jpeg(tag: str) -> bytes:
    color = _COLORS.get(tag, _COLORS["person"])
    img = Image.new("RGB", (_WIDTH, _HEIGHT), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _ensure_user(db) -> User:
    user = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if user is None:
        user = User(
            email=DEMO_EMAIL,
            name="Demo Admin",
            password_hash=hash_password(DEMO_PASSWORD),
            role="ADMIN",
            is_active=True,
        )
        db.add(user)
        db.flush()
    return user


def _ensure_camera(db, user_id: int) -> Camera:
    cam = db.query(Camera).filter(Camera.camera_name == DEMO_CAMERA).first()
    if cam is None:
        cam = Camera(
            camera_name=DEMO_CAMERA,
            location=DEMO_CAMERA_LOCATION,
            description="Phase 6 demo evidence camera",
            camera_type="CCTV",
            is_live=False,
            stream_status="OFFLINE",
            created_by_user_id=user_id,
        )
        db.add(cam)
        db.flush()
    return cam


def _ensure_video(db, camera_id: int) -> Video:
    video = db.query(Video).filter(Video.filename == DEMO_VIDEO).first()
    if video is None:
        video = Video(
            filename=DEMO_VIDEO,
            storage_path=f"demo/{DEMO_VIDEO}",
            camera_id=camera_id,
            duration_seconds=600.0,
            width=_WIDTH,
            height=_HEIGHT,
            fps=5.0,
            status="READY",
        )
        db.add(video)
        db.flush()
    return video


def _ensure_investigation(db, user_id: int, video_id: int) -> Investigation:
    inv = (
        db.query(Investigation)
        .filter(Investigation.title == DEMO_INVESTIGATION_TITLE)
        .first()
    )
    if inv is None:
        inv = Investigation(
            title=DEMO_INVESTIGATION_TITLE,
            description="Phase 6 video-RAG demo case",
            query=DEMO_INVESTIGATION_QUERY,
            video_id=video_id,
            status="OPEN",
            created_by_user_id=user_id,
        )
        db.add(inv)
        db.flush()
    return inv


def _ensure_session(db, camera_id: int, user_id: int, frames: int) -> CameraSession:
    session = (
        db.query(CameraSession)
        .filter(CameraSession.camera_id == camera_id, CameraSession.transport == "simulation")
        .filter(CameraSession.frames_received > 0)
        .order_by(CameraSession.id.desc())
        .first()
    )
    if session is None:
        session = CameraSession(
            camera_id=camera_id,
            status="COMPLETED",
            transport="simulation",
            fps_target=5.0,
            started_by_user_id=user_id,
            started_at=datetime.utcnow(),
            stopped_at=datetime.utcnow(),
            frames_received=frames,
            frames_sampled=frames,
            frames_buffered=frames,
        )
        db.add(session)
        db.flush()
    return session


def _wipe_demo_evidence(db) -> None:
    rows = (
        db.query(ForensicEvidence)
        .filter(ForensicEvidence.public_id.like("EVD-DEMO-%"))
        .all()
    )
    for row in rows:
        qdrant.delete("video_evidence", row.public_id)
        db.delete(row)
    obs = (
        db.query(VlmObservationRecord)
        .filter(VlmObservationRecord.observation_id.like("VLM-DEMO-%"))
        .all()
    )
    for o in obs:
        db.delete(o)


def _store_jpeg(db, public_id: str, camera_id: int, session_id: Optional[int], tag: str) -> Dict:
    data = _make_jpeg(tag)
    sha = sha256_bytes(data)
    object_name = evidence_object_name(public_id, camera_id, session_id, _EXT)
    stored_path = storage.put_bytes(_BUCKET, data, object_name, content_type=_MIME, lock=False)
    return {
        "storage_path": stored_path,
        "sha256": sha,
        "size_bytes": len(data),
        "width": _WIDTH,
        "height": _HEIGHT,
    }


def _insert_evidence(
    db,
    *,
    evidence_type: str,
    camera_id: int,
    session_id: Optional[int],
    event_id: Optional[str],
    event_type: Optional[str],
    tracking_id: Optional[str],
    frame_sequence: Optional[int],
    frame_timestamp: Optional[float],
    window_start: Optional[float],
    window_end: Optional[float],
    vlm_observation_id: Optional[str],
    content_text: str,
    metadata: Dict,
    tag: str,
) -> ForensicEvidence:
    public_id = f"EVD-DEMO-{uuid.uuid4().hex[:8]}"
    stored = _store_jpeg(db, public_id, camera_id, session_id, tag)
    captured_at = datetime.utcnow()
    provenance = build_provenance(
        public_id=public_id,
        evidence_type=evidence_type,
        source="DERIVED",
        camera_id=camera_id,
        session_id=session_id,
        event_id=event_id,
        event_type=event_type,
        tracking_id=tracking_id,
        frame_sequence=frame_sequence,
        frame_timestamp=frame_timestamp,
        vlm_observation_id=vlm_observation_id,
        source_frame_ids=[frame_sequence] if frame_sequence is not None else [],
        window_start=window_start,
        window_end=window_end,
        captured_at=captured_at.isoformat(),
        storage_path=stored["storage_path"],
        mime_type=_MIME,
        width=stored["width"],
        height=stored["height"],
        sha256=stored["sha256"],
        size_bytes=stored["size_bytes"],
    )
    row = ForensicEvidence(
        public_id=public_id,
        evidence_type=evidence_type,
        source="DERIVED",
        camera_id=camera_id,
        session_id=session_id,
        event_id=event_id,
        event_type=event_type,
        tracking_id=tracking_id,
        frame_sequence=frame_sequence,
        frame_timestamp=frame_timestamp,
        window_start=window_start,
        window_end=window_end,
        vlm_observation_id=vlm_observation_id,
        source_frame_ids="[]",
        captured_at=captured_at,
        storage_path=stored["storage_path"],
        mime_type=_MIME,
        width=stored["width"],
        height=stored["height"],
        sha256=stored["sha256"],
        size_bytes=stored["size_bytes"],
        content_text=content_text,
        extra_metadata=serialize_metadata(metadata),
        provenance=serialize_provenance(provenance),
        index_status=IndexStatus.INDEXED.value,
        indexed_at=captured_at,
    )
    db.add(row)
    db.flush()
    _index(row, content_text, tag)
    return row


def _index(row: ForensicEvidence, text: str, tag: str) -> None:
    vec = embeddings.embed_text(text or f"evidence {row.public_id}")
    label = "" if tag == "observation" else tag
    payload = evidence_index_payload(
        evidence_id=row.public_id,
        evidence_type=row.evidence_type,
        source=row.source,
        camera_id=row.camera_id,
        session_id=row.session_id,
        timestamp=row.frame_timestamp,
        event_id=row.event_id,
        event_type=row.event_type,
        tracking_id=row.tracking_id,
        frame_sequence=row.frame_sequence,
        vlm_observation_id=row.vlm_observation_id,
        storage_path=row.storage_path,
        sha256=row.sha256,
        source_text=text,
        object_class=label or None,
    )
    qdrant.index_evidence(row.public_id, vec, payload)


def seed_demo_evidence(db=None) -> Dict:
    """Seed (or reseed) the DEMO-PHASE6 evidence set; returns a manifest."""
    own = db is None
    db = db or SessionLocal()
    try:
        _wipe_demo_evidence(db)
        user = _ensure_user(db)
        db.flush()
        camera = _ensure_camera(db, user.id)
        db.flush()
        video = _ensure_video(db, camera.id)
        db.flush()
        investigation = _ensure_investigation(db, user.id, video.id)
        db.flush()

        n_events = len(_EVENTS)
        session = _ensure_session(db, camera.id, user.id, n_events + 2)

        created = 0
        track_ids = {"person": [], "car": []}
        for i, ev in enumerate(_EVENTS):
            ts = float(ev["ts"])
            frame = int((ts - _T0) / 2)
            label = ev["label"]
            row = _insert_evidence(
                db,
                evidence_type="TRACK_EVENT",
                camera_id=camera.id,
                session_id=session.id,
                event_id=f"EV-DEMO-{i:04d}",
                event_type=ev["event_type"],
                tracking_id=ev["tracking_id"],
                frame_sequence=frame,
                frame_timestamp=ts,
                window_start=None,
                window_end=None,
                vlm_observation_id=None,
                content_text=track_event_content(_EventLike(ev), camera.camera_name),
                metadata={"state": ev["state"], "label": label, "_demo": True, "tag": "DEMO"},
                tag=label,
            )
            track_ids.setdefault(label, []).append(ev["tracking_id"])
            created += 1

        obs_row = _insert_evidence(
            db,
            evidence_type="VLM_OBSERVATION",
            camera_id=camera.id,
            session_id=session.id,
            event_id=_OBSERVATION["trigger_detail"],
            event_type=None,
            tracking_id=None,
            frame_sequence=None,
            frame_timestamp=_OBSERVATION["window_end"],
            window_start=_OBSERVATION["window_start"],
            window_end=_OBSERVATION["window_end"],
            vlm_observation_id=_OBSERVATION["observation_id"],
            content_text=observation_content(_OBSERVATION),
            metadata={"_demo": True, "tag": "DEMO"},
            tag="observation",
        )
        _persist_observation_record(db, _OBSERVATION, camera.id, session.id)
        created += 1

        db.commit()
        return {
            "camera_id": camera.id,
            "camera_name": camera.camera_name,
            "video_id": video.id,
            "session_id": session.id,
            "case_id": investigation.id,
            "user_id": user.id,
            "user_email": DEMO_EMAIL,
            "user_password": DEMO_PASSWORD,
            "tracking_ids": {k: sorted(set(v)) for k, v in track_ids.items()},
            "evidence_created": created,
        }
    finally:
        if own:
            db.close()


def _persist_observation_record(db, payload: Dict, camera_id: int, session_id: int) -> None:
    import json

    row = VlmObservationRecord(
        observation_id=str(payload["observation_id"]),
        request_id=payload.get("request_id"),
        camera_id=camera_id,
        session_id=session_id,
        trigger=payload.get("trigger"),
        trigger_detail=payload.get("trigger_detail"),
        summary=payload.get("summary"),
        items=json.dumps(payload.get("items") or []),
        notes=json.dumps(payload.get("notes") or []),
        model=payload.get("model"),
        provider_mode=payload.get("provider_mode"),
        source_frames=json.dumps(payload.get("source_frames") or []),
        window_start=payload.get("window_start"),
        window_end=payload.get("window_end"),
    )
    db.add(row)


class _EventLike:
    def __init__(self, ev: Dict) -> None:
        self.event_type = ev["event_type"]
        self.tracking_id = ev["tracking_id"]
        self.frame_index = int((float(ev["ts"]) - _T0) / 2)
        self.metadata = {"label": ev["label"], "state": ev["state"]}


def main() -> None:
    manifest = seed_demo_evidence()
    print("Seeded DEMO-PHASE6 forensic evidence:")
    for key, value in manifest.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
