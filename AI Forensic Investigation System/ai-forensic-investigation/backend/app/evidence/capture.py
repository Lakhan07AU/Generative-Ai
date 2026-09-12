"""Per-session evidence capture (Phase 5).

Converts live AI observations into durable, traceable forensic evidence:

  * tracking events -> TRACK_EVENT evidence (visual + event + provenance)
  * VLM observations -> persisted observation record + FRAME source evidence +
    VLM_OBSERVATION evidence (the grounded text + provenance)

Capture decisions:
  * Only the MINIMUM visual content is stored: one encoded JPEG copy per
    evidence record (copy-encoded, never the raw buffer, never the original
    source object). The event/observation window is preserved as metadata.
  * Exact re-captures of identical bytes on the same camera+session are
    deduplicated (existing object is reused; no duplicate object written).
  * Every captured record is enqueued for async vector indexing (bounded queue).
  * Server-generated provenance is authoritative; client input is never trusted.

Capture never blocks the live pipeline: it runs on the VLM worker / tracking
threads and does its own short DB sessions. Any failure is contained.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.live.rolling_buffer import FrameEntry, RollingFrameBuffer
from app.storage.service import storage
from app.vlm.preprocess import encode_frames
from app.vlm.selection import select_for_event

from app.evidence.indexer import EvidenceIndexQueue, evidence_indexer
from app.evidence.paths import dedup_identity, evidence_object_name, sha256_bytes
from app.evidence.schemas import (
    EvidenceSource,
    EvidenceType,
    IndexStatus,
    build_provenance,
    frame_content,
    observation_content,
    parse_metadata,
    serialize_metadata,
    serialize_provenance,
    track_event_content,
)

logger = logging.getLogger(__name__)

_BUCKET = "frames"
_EXT = ".jpg"
_MIME = "image/jpeg"


class EvidenceCapture:
    """One live session's evidence capturer + observation persister."""

    def __init__(self, runtime, queue: Optional[EvidenceIndexQueue] = None) -> None:
        self._runtime = runtime
        self._queue = queue if queue is not None else evidence_indexer
        self._lock = threading.RLock()
        self._started = False

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        with self._lock:
            self._started = True

    def stop(self) -> None:
        with self._lock:
            self._started = False

    @property
    def enabled(self) -> bool:
        with self._lock:
            return bool(self._started and getattr(settings, "EVIDENCE_ENABLED", True))

    def counts(self, db=None) -> dict:
        from app.database.models import ForensicEvidence

        try:
            session_id = self._runtime.session_db_id
            own = db is None
            db = db or _db()
            try:
                q = db.query(ForensicEvidence).filter(ForensicEvidence.session_id == session_id)
                total = q.count()
                indexed = q.filter(ForensicEvidence.index_status == IndexStatus.INDEXED.value).count()
                failed = q.filter(ForensicEvidence.index_status == IndexStatus.FAILED.value).count()
                return {
                    "evidence_enabled": self.enabled,
                    "evidence_captured": total,
                    "evidence_indexed": indexed,
                    "evidence_failed": failed,
                }
            finally:
                if own:
                    db.close()
        except Exception:  # noqa: BLE001 - status counts must never fail a snapshot
            return {
                "evidence_enabled": self.enabled,
                "evidence_captured": 0,
                "evidence_indexed": 0,
                "evidence_failed": 0,
            }

    # ------------------------------------------------------------ capture hook

    def on_event(self, event) -> Optional[str]:
        """Capture TRACK_EVENT evidence for a fired tracking event."""
        if not self.enabled:
            return None
        try:
            selection = select_for_event(
                self._runtime.buffer,
                event,
                max_frames=int(getattr(settings, "EVIDENCE_MAX_FRAMES_PER_CAPTURE", 1)),
            )
            if not selection.frames:
                return None
            entry = _trigger_entry(self._runtime.buffer, event, selection.frames)
            if entry is None:
                return None
            row = self._capture_from_entry(
                db=None,
                entry=entry,
                evidence_type=EvidenceType.TRACK_EVENT.value,
                source=EvidenceSource.DERIVED.value,
                event_id=event.event_id,
                event_type=event.event_type,
                tracking_id=event.tracking_id,
                frame_sequence=entry.sequence,
                frame_timestamp=entry.timestamp,
                window_start=selection.window_start,
                window_end=selection.window_end,
                content_text=track_event_content(event, self._runtime.camera_name),
                extra_meta={
                    "state": (event.metadata or {}).get("state"),
                    "label": (event.metadata or {}).get("label"),
                    "event_camera_id": event.camera_id,
                    "event_session_id": event.session_id,
                },
            )
            return row.public_id if row is not None else None
        except Exception as exc:  # noqa: BLE001 - capture must never take the pipeline down
            logger.warning("Event evidence capture failed (camera=%s): %s", self._runtime.camera_id, exc)
            return None

    def on_observation(self, payload: dict) -> Optional[str]:
        """Persist a VLM observation + capture its source frames as evidence."""
        if not self.enabled:
            return None
        try:
            obs_id = payload.get("observation_id")
            if not obs_id:
                return None
            db = _db()
            try:
                if _observation_exists(db, obs_id):
                    return None
                self._persist_observation(db, payload)
            finally:
                db.close()

            # Capture each source frame as FRAME evidence (exact re-captures dedup).
            entry_by_seq = _sequence_index(self._runtime.buffer)
            captured_frames: List[int] = []
            for src in (payload.get("source_frames") or []):
                seq = src.get("sequence")
                entry = entry_by_seq.get(seq)
                if entry is None:
                    continue
                public_id = self._capture_from_entry(
                    db=None,
                    entry=entry,
                    evidence_type=EvidenceType.FRAME.value,
                    source=EvidenceSource.RAW_SOURCE.value,
                    vlm_observation_id=obs_id,
                    frame_sequence=entry.sequence,
                    frame_timestamp=entry.timestamp,
                    content_text=frame_content(
                        self._runtime.camera_id,
                        self._runtime.camera_name,
                        self._runtime.session_db_id,
                        entry.sequence,
                    ),
                    extra_meta={"source": "vlm_observation"},
                )
                if public_id:
                    captured_frames.append(entry.sequence)

            # VLM_OBSERVATION evidence: grounded text + best available visual.
            self._capture_observation_evidence(
                db=None,
                payload=payload,
                observation_id=obs_id,
                captured_frame_sequences=captured_frames,
            )
            return obs_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("Observation evidence capture failed (camera=%s): %s", self._runtime.camera_id, exc, exc_info=True)
            return None

    # --------------------------------------------------------------- internals

    def _capture_observation_evidence(
        self,
        db,
        payload: Dict[str, Any],
        observation_id: str,
        captured_frame_sequences: List[int],
    ) -> Optional[str]:
        entries = _sequence_index(self._runtime.buffer)
        best: Optional[FrameEntry] = None
        for seq in captured_frame_sequences:
            candidate = entries.get(seq)
            if candidate is not None:
                best = candidate
                break
        if best is None:
            for src in (payload.get("source_frames") or []):
                candidate = entries.get(src.get("sequence"))
                if candidate is not None:
                    best = candidate
                    break
        window = {
            "window_start": payload.get("window_start"),
            "window_end": payload.get("window_end"),
        } if payload.get("window_start") is not None or payload.get("window_end") is not None else {}
        row = self._capture_from_entry(
            db=db,
            entry=best,
            evidence_type=EvidenceType.VLM_OBSERVATION.value,
            source=EvidenceSource.DERIVED.value,
            vlm_observation_id=observation_id,
            frame_sequence=best.sequence if best is not None else None,
            frame_timestamp=best.timestamp if best is not None else None,
            window_start=window.get("window_start"),
            window_end=window.get("window_end"),
            content_text=observation_content(payload),
            source_frame_ids=captured_frame_sequences or _source_frame_sequences(payload),
            extra_meta={
                "trigger": payload.get("trigger"),
                "trigger_detail": payload.get("trigger_detail"),
                "provider_mode": payload.get("provider_mode"),
                "model": payload.get("model"),
                "statement_count": len(payload.get("items") or []),
            },
        )
        return row.public_id if row is not None else None

    def _capture_from_entry(
        self,
        db,
        entry: Optional[FrameEntry],
        *,
        evidence_type: str,
        source: str,
        event_id: Optional[str] = None,
        event_type: Optional[str] = None,
        tracking_id: Optional[str] = None,
        frame_sequence: Optional[int] = None,
        frame_timestamp: Optional[float] = None,
        window_start: Optional[float] = None,
        window_end: Optional[float] = None,
        vlm_observation_id: Optional[str] = None,
        source_frame_ids: Optional[List[int]] = None,
        content_text: str = "",
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Encode, store (dedup), and persist one evidence record.

        ``entry is None`` is used for metadata-only evidence (no visual object).

        The whole check-store-commit sequence is serialized per capture instance
        (``self._lock``) so two concurrent captures of identical bytes on the same
        runtime cannot both pass the dedup check before either commits: the second
        one deterministically reuses the first object.
        """
        from app.database.models import ForensicEvidence

        with self._lock:
            local_db = db is None
            db = db or _db()
            try:
                public_id = new_evidence_id()
                stored = None
                if entry is not None:
                    stored = _encode_and_store(db, entry, public_id, self._runtime)
                metadata = dict(extra_meta or {})
                metadata.update(
                    {
                        "frame_width": stored["width"] if stored else None,
                        "frame_height": stored["height"] if stored else None,
                        "dedup_reused": bool(stored and stored.get("reused")),
                    }
                )
                captured_at = datetime.utcnow()
                provenance = build_provenance(
                    public_id=public_id,
                    evidence_type=evidence_type,
                    source=source,
                    camera_id=self._runtime.camera_id,
                    session_id=self._runtime.session_db_id,
                    event_id=event_id,
                    event_type=event_type,
                    tracking_id=tracking_id,
                    frame_sequence=frame_sequence,
                    frame_timestamp=frame_timestamp,
                    vlm_observation_id=vlm_observation_id,
                    source_frame_ids=source_frame_ids or [],
                    window_start=window_start,
                    window_end=window_end,
                    captured_at=captured_at.isoformat(),
                    storage_path=stored["storage_path"] if stored else None,
                    mime_type=_MIME if stored else None,
                    width=stored["width"] if stored else None,
                    height=stored["height"] if stored else None,
                    sha256=stored["sha256"] if stored else None,
                    size_bytes=stored["size_bytes"] if stored else None,
                )
                row = ForensicEvidence(
                    public_id=public_id,
                    evidence_type=evidence_type,
                    source=source,
                    camera_id=self._runtime.camera_id,
                    session_id=self._runtime.session_db_id,
                    event_id=event_id,
                    event_type=event_type,
                    tracking_id=tracking_id,
                    frame_sequence=frame_sequence,
                    frame_timestamp=frame_timestamp,
                    window_start=window_start,
                    window_end=window_end,
                    vlm_observation_id=vlm_observation_id,
                    source_frame_ids=json.dumps(source_frame_ids or []),
                    captured_at=captured_at,
                    storage_path=stored["storage_path"] if stored else None,
                    mime_type=_MIME if stored else None,
                    width=stored["width"] if stored else None,
                    height=stored["height"] if stored else None,
                    sha256=stored["sha256"] if stored else None,
                    size_bytes=stored["size_bytes"] if stored else None,
                    content_text=content_text,
                    extra_metadata=serialize_metadata(metadata),
                    provenance=serialize_provenance(provenance),
                    index_status=IndexStatus.PENDING.value,
                )
                db.add(row)
                db.commit()
                db.refresh(row)
                self._queue.submit(row.id, row.public_id)
                return row
            except Exception:
                db.rollback()
                raise
            finally:
                if local_db:
                    db.close()

    def _persist_observation(self, db, payload: Dict[str, Any]) -> None:
        from app.database.models import VlmObservationRecord

        row = VlmObservationRecord(
            observation_id=str(payload["observation_id"]),
            request_id=payload.get("request_id"),
            camera_id=payload.get("camera_id"),
            session_id=payload.get("session_id"),
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
        db.commit()


def _db():
    from app.database.session import SessionLocal

    return SessionLocal()


def _observation_exists(db, observation_id: str) -> bool:
    from app.database.models import VlmObservationRecord

    return (
        db.query(VlmObservationRecord)
        .filter(VlmObservationRecord.observation_id == observation_id)
        .first()
        is not None
    )


def _trigger_entry(buffer: RollingFrameBuffer, event, frames: List[FrameEntry]) -> Optional[FrameEntry]:
    """Prefer the exact trigger frame; else the first selected frame."""
    if event.frame_index:
        for entry in frames:
            if entry.sequence == event.frame_index:
                return entry
    return frames[0] if frames else buffer.latest()


def _sequence_index(buffer: RollingFrameBuffer) -> Dict[int, FrameEntry]:
    return {entry.sequence: entry for entry in buffer.snapshot()}


def _source_frame_sequences(payload: Dict[str, Any]) -> List[int]:
    out = []
    for src in (payload.get("source_frames") or []):
        seq = src.get("sequence")
        if isinstance(seq, int):
            out.append(seq)
    return out


def _encode_and_store(db, entry: FrameEntry, public_id: str, runtime) -> Dict[str, Any]:
    """Copy-encode one buffered frame to JPEG, hash it, store (dedup) it."""
    prepared, _ = encode_frames(
        [entry],
        max_side=int(getattr(settings, "EVIDENCE_MAX_IMAGE_SIDE", 1280)),
        jpeg_quality=int(getattr(settings, "EVIDENCE_JPEG_QUALITY", 92)),
        max_bytes=int(getattr(settings, "EVIDENCE_MAX_IMAGE_BYTES", 1024 * 1024)),
    )
    if not prepared:
        raise ValueError("frame could not be encoded for evidence capture")
    frame = prepared[0]
    data = frame.data
    sha = sha256_bytes(data)

    from app.database.models import ForensicEvidence

    existing = (
        db.query(ForensicEvidence)
        .filter(
            ForensicEvidence.camera_id == runtime.camera_id,
            ForensicEvidence.session_id == runtime.session_db_id,
            ForensicEvidence.sha256 == sha,
        )
        .order_by(ForensicEvidence.id.asc())
        .first()
    )
    if existing is not None and existing.storage_path:
        _reuse_metadata(existing, sha)
        return {
            "storage_path": existing.storage_path,
            "sha256": sha,
            "size_bytes": len(data),
            "width": existing.width or frame.width,
            "height": existing.height or frame.height,
            "reused": True,
        }

    object_name = evidence_object_name(public_id, runtime.camera_id, runtime.session_db_id, _EXT)
    stored_path = storage.put_bytes(_BUCKET, data, object_name, content_type=_MIME, lock=False)
    return {
        "storage_path": stored_path,
        "sha256": sha,
        "size_bytes": len(data),
        "width": frame.width,
        "height": frame.height,
        "reused": False,
    }


def _reuse_metadata(row, sha256: str) -> None:
    # Record the shared object so future index retries see its identity too.
    try:
        if not row.sha256:
            row.sha256 = sha256
    except Exception:  # noqa: BLE001
        pass


def new_evidence_id() -> str:
    return f"EVD-{uuid.uuid4().hex[:12]}"


# re-export for tests
dedup_key = dedup_identity