"""Async evidence vector-index worker (Phase 5).

Index flow::

    Evidence Created
        -> submit()      sets index_status=PENDING and enqueues
        -> worker        marks INDEXING
        -> embed         embeddings.embed_text(content_text)
        -> qdrant        qdrant.index_evidence(id, vec, payload)
        -> INDEXED

Transient failures retry with backoff up to EVIDENCE_INDEX_MAX_ATTEMPTS before
the record is marked FAILED (the evidence itself is never lost; a FAILED record
can be re-submitted via the API). Qdrant being down never stops capture: rows
stay PENDING/FAILED and storage still succeeds. The queue is bounded - when full
the OLDEST job is evicted (backpressure) and counted, so a runaway index load
cannot grow memory unboundedly.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class IndexJob:
    evidence_id: int
    public_id: str


class EvidenceIndexQueue:
    """One bounded drain of evidence records waiting for vector indexing."""

    def __init__(
        self,
        maxsize: Optional[int] = None,
        max_attempts: Optional[int] = None,
        backoff_seconds: Optional[float] = None,
        clock=None,
    ) -> None:
        self._maxsize = max(1, int(maxsize if maxsize is not None else settings.EVIDENCE_INDEX_QUEUE_SIZE))
        self._max_attempts = max(1, int(max_attempts if max_attempts is not None else settings.EVIDENCE_INDEX_MAX_ATTEMPTS))
        self._backoff = float(backoff_seconds if backoff_seconds is not None else settings.EVIDENCE_INDEX_RETRY_BACKOFF_SECONDS)
        self._clock = clock or time.monotonic

        self._queue: Deque[IndexJob] = deque()
        self._lock = threading.Condition(threading.Lock())
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._indexed = 0
        self._failed = 0
        self._dropped = 0
        self._errors = 0

    # -------------------------------------------------------------- control

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="evidence-index-worker",
            daemon=True,
        )
        self._thread.start()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        with self._lock:
            self._queue.clear()
            self._lock.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def clear(self) -> None:
        with self._lock:
            self._queue.clear()

    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    # ------------------------------------------------------------ submission

    def submit(self, evidence_id: int, public_id: str) -> bool:
        """Ensure the queue is running and enqueue a job (drop-oldest on full).

        Returns True when accepted (possibly after an eviction), False when the
        worker could not be started.
        """
        self.start()
        if not self.running:
            return False
        self._reset_status(evidence_id)
        with self._lock:
            if len(self._queue) >= self._maxsize:
                self._queue.popleft()
                self._dropped += 1
            self._queue.append(IndexJob(evidence_id=evidence_id, public_id=public_id))
            self._lock.notify()
        return True

    @staticmethod
    def _reset_status(evidence_id: int) -> None:
        try:
            from app.database.session import SessionLocal
            from app.database.models import ForensicEvidence

            db = SessionLocal()
            try:
                row = db.query(ForensicEvidence).filter(ForensicEvidence.id == evidence_id).first()
                if row is not None:
                    row.index_status = "PENDING"
                    row.index_error = None
                    db.commit()
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001 - status reset is best-effort
            logger.warning("Could not reset index status for evidence %s: %s", evidence_id, exc)

    # --------------------------------------------------------------- metrics

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "queue_size": len(self._queue),
                "total_indexed": self._indexed,
                "total_failed": self._failed,
                "total_dropped": self._dropped,
                "total_errors": self._errors,
            }

    # ------------------------------------------------------------------- run

    def _run(self) -> None:
        while not self._stop.is_set():
            job: Optional[IndexJob] = None
            with self._lock:
                while not self._queue and not self._stop.is_set():
                    self._lock.wait(timeout=1.0)
                if self._queue:
                    job = self._queue.popleft()
            if job is None:
                continue
            try:
                self._process(job)
            except Exception as exc:  # noqa: BLE001 - index worker must never die
                logger.warning("Evidence index worker error (evidence=%s): %s", job.public_id, exc)
                with self._lock:
                    self._errors += 1
                self._mark_failed(job.evidence_id, str(exc))

    def _process(self, job: IndexJob) -> None:
        from app.ai.embeddings import embeddings
        from app.ai.qdrant_service import qdrant
        from app.database.models import ForensicEvidence
        from app.database.session import SessionLocal
        from app.evidence.schemas import (
            evidence_index_payload,
            parse_metadata,
        )

        last_error = None
        for attempt in range(1, self._max_attempts + 1):
            if self._stop.is_set():
                return
            db = SessionLocal()
            try:
                row = db.query(ForensicEvidence).filter(ForensicEvidence.id == job.evidence_id).first()
                if row is None:
                    logger.warning("Evidence row gone while indexing (%s); dropping job", job.public_id)
                    return
                row.index_status = "INDEXING"
                row.index_attempts = attempt
                row.last_index_attempt_at = _utcnow()
                row.index_error = None
                db.commit()

                text = (row.content_text or "").strip()
                vec = embeddings.embed_text(text or f"evidence {job.public_id}")
                if len(vec) != embeddings.embed_dim():
                    raise ValueError(
                        f"embedding dimension {len(vec)} != collection dimension {embeddings.embed_dim()}"
                    )
                meta = parse_metadata(row)
                object_class = (meta.get("label") or "").strip().lower() or None
                payload = evidence_index_payload(
                    evidence_id=row.public_id,
                    evidence_type=row.evidence_type,
                    source=row.source,
                    camera_id=row.camera_id,
                    session_id=row.session_id,
                    timestamp=row.frame_timestamp if row.frame_timestamp is not None else None,
                    event_id=row.event_id,
                    event_type=row.event_type,
                    tracking_id=row.tracking_id,
                    frame_sequence=row.frame_sequence,
                    vlm_observation_id=row.vlm_observation_id,
                    storage_path=row.storage_path,
                    sha256=row.sha256,
                    source_text=text,
                    object_class=object_class,
                )
                qdrant.index_evidence(str(row.public_id), vec, payload)
                row.index_status = "INDEXED"
                row.indexed_at = _utcnow()
                row.index_error = None
                db.commit()
                with self._lock:
                    self._indexed += 1
                logger.debug("Indexed evidence %s (%s)", row.public_id, row.evidence_type)
                return
            except Exception as exc:  # noqa: BLE001 - retry transient failures
                last_error = str(exc)
                logger.warning(
                    "Evidence index attempt %s/%s failed (%s): %s",
                    attempt,
                    self._max_attempts,
                    job.public_id,
                    exc,
                )
                try:
                    db.rollback()
                    row = db.query(ForensicEvidence).filter(ForensicEvidence.id == job.evidence_id).first()
                    if row is not None:
                        row.index_status = "PENDING"
                        row.last_index_attempt_at = _utcnow()
                        db.commit()
                except Exception:  # noqa: BLE001
                    pass
                if attempt < self._max_attempts:
                    time.sleep(self._backoff * attempt)
            finally:
                db.close()
        self._mark_failed(job.evidence_id, str(last_error))

    def _mark_failed(self, evidence_id: int, error: str) -> None:
        try:
            from app.database.models import ForensicEvidence
            from app.database.session import SessionLocal

            db = SessionLocal()
            try:
                row = db.query(ForensicEvidence).filter(ForensicEvidence.id == evidence_id).first()
                if row is not None:
                    row.index_status = "FAILED"
                    row.index_error = (error or "index failed")[:2000]
                    row.last_index_attempt_at = _utcnow()
                    db.commit()
            finally:
                db.close()
            with self._lock:
                self._failed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not mark evidence %s FAILED: %s", evidence_id, exc)


def _utcnow():
    from datetime import datetime

    return datetime.utcnow()


evidence_indexer = EvidenceIndexQueue()