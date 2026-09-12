"""Test helpers for Phase 6 investigation search tests.

Seeds ForensicEvidence rows through the same seams the production indexer uses
(embed_content -> qdrant.index_evidence with the real payload builder) so
retrieval behaves exactly like production with the in-memory qdrant fallback.
"""

from __future__ import annotations

import uuid

from app.ai.embeddings import embeddings
from app.ai.qdrant_service import qdrant
from app.database import models
from app.database.models import ForensicEvidence
from app.evidence.schemas import (
    build_provenance,
    evidence_index_payload,
    serialize_metadata,
    serialize_provenance,
)


def seed_evidence(
    db,
    *,
    camera_id: int,
    session_id: int,
    evidence_type: str = "TRACK_EVENT",
    source: str = "DERIVED",
    event_type: str = "object_entered",
    event_id: str | None = None,
    tracking_id: str | None = None,
    label: str | None = None,
    timestamp: float,
    content_text: str | None = None,
    vlm_observation_id: str | None = None,
    index: bool = True,
    storage_path: str | None = "demo/objects/jpeg.jpg",
) -> ForensicEvidence:
    public_id = f"EVD-{uuid.uuid4().hex[:12]}"
    meta: dict = {}
    if label:
        meta["label"] = label
    provenance = build_provenance(
        public_id=public_id,
        evidence_type=evidence_type,
        source=source,
        camera_id=camera_id,
        session_id=session_id,
        event_id=event_id,
        event_type=event_type,
        tracking_id=tracking_id,
        frame_sequence=1,
        frame_timestamp=timestamp,
        vlm_observation_id=vlm_observation_id,
        source_frame_ids=[],
        window_start=timestamp,
        window_end=timestamp,
        captured_at="2026-01-01T00:00:00",
        storage_path=storage_path,
        mime_type="image/jpeg",
        width=320,
        height=240,
        sha256="a" * 64,
        size_bytes=1234,
    )
    text = content_text if content_text is not None else (
        f"{event_type} tracking_id={tracking_id or 'T-0'} camera=cam label={label or ''}"
    ).strip()
    row = ForensicEvidence(
        public_id=public_id,
        evidence_type=evidence_type,
        source=source,
        camera_id=camera_id,
        session_id=session_id,
        event_id=event_id,
        event_type=event_type,
        tracking_id=tracking_id,
        frame_sequence=1,
        frame_timestamp=timestamp,
        window_start=timestamp,
        window_end=timestamp,
        vlm_observation_id=vlm_observation_id,
        source_frame_ids="[]",
        storage_path=storage_path,
        mime_type="image/jpeg",
        width=320,
        height=240,
        sha256="a" * 64,
        size_bytes=1234,
        content_text=text,
        extra_metadata=serialize_metadata(meta),
        provenance=serialize_provenance(provenance),
        index_status="INDEXED",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    if index:
        vec = embeddings.embed_text(row.content_text or f"evidence {public_id}")
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
            source_text=row.content_text,
            object_class=(label or "").lower() or None,
        )
        qdrant.index_evidence(str(row.public_id), vec, payload)
    return row


def make_video_and_investigation(db, camera_id: int, user_id: int) -> models.Investigation:
    video = models.Video(
        filename="case.mp4",
        storage_path="demo/case.mp4",
        camera_id=camera_id,
        status="READY",
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    inv = models.Investigation(
        title="Case",
        description="test case",
        query="demo query",
        video_id=video.id,
        status="OPEN",
        created_by_user_id=user_id,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


def user_id_by_email(db, email: str) -> int:
    row = db.query(models.User).filter(models.User.email == email).first()
    assert row is not None, f"user {email} not found"
    return row.id