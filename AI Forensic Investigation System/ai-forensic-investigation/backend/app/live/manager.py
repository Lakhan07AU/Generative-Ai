"""Live session state machine + manager (Phase 1).

A :class:`LiveSessionRuntime` owns one camera's ingest pipeline
(LiveCameraSource -> FrameIngestion -> FrameSampler -> RollingFrameBuffer) and
tracks the real-time session state. :class:`LiveCameraManager` maps camera ids
to runtimes and guarantees at most ONE active session per camera.
"""

import asyncio
import logging
import threading
import time
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.live.rolling_buffer import RollingFrameBuffer
from app.live.sampler import FrameSampler
from app.live.ingestion import FrameIngestion
from app.live.source import LiveCameraSource

logger = logging.getLogger(__name__)


class _Subscriber:
    """A status/detection subscriber: an asyncio.Queue + the loop that owns it.

    Publishing is made thread-safe by scheduling the queue put on the owning
    loop with ``loop.call_soon_threadsafe`` (safe from REST threadpool threads,
    the WebRTC receive task, and the simulation feeder thread alike).
    """

    __slots__ = ("queue", "loop")

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self.loop: asyncio.AbstractEventLoop | None = None


def _publish_item(item, queue: asyncio.Queue) -> None:
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(item)
        except Exception:  # noqa: BLE001
            pass


class SessionStatus(str, Enum):
    CREATED = "CREATED"
    CONNECTING = "CONNECTING"
    LIVE = "LIVE"
    STOPPING = "STOPPING"
    DISCONNECTED = "DISCONNECTED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"

    @classmethod
    def active_values(cls) -> List[str]:
        return ["CREATED", "CONNECTING", "LIVE", "STOPPING"]


def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


class LiveSessionRuntime:
    """In-memory live ingest session for one camera."""

    def __init__(
        self,
        camera_id: int,
        camera_name: str,
        started_by_user_id: Optional[int],
        transport: str = "webrtc",
        fps_target: Optional[float] = None,
        window_seconds: Optional[float] = None,
        max_frames: Optional[int] = None,
        source_fps_cap: Optional[float] = None,
        clock=None,
    ) -> None:
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.started_by_user_id = started_by_user_id
        self.transport = transport
        self.fps_target = float(fps_target or settings.LIVE_SESSION_FPS)
        self.window_seconds = float(window_seconds or settings.LIVE_BUFFER_WINDOW_SECONDS)
        self.max_frames = int(max_frames or settings.LIVE_BUFFER_MAX_FRAMES)
        self.source_fps_cap = float(source_fps_cap or settings.LIVE_SOURCE_FPS_CAP)
        self.max_frame_bytes = int(settings.LIVE_MAX_FRAME_BYTES)

        self.session_db_id: Optional[int] = None
        self.status = SessionStatus.CREATED
        self.error: Optional[str] = None
        self.started_at = _utcnow_iso()
        self.updated_at = self.started_at
        self.stopped_at: Optional[str] = None

        self.sampler = FrameSampler(target_fps=self.fps_target)
        self.buffer = RollingFrameBuffer(
            window_seconds=self.window_seconds,
            max_frames=self.max_frames,
            clock=clock,
        )
        self.ingestion = FrameIngestion(
            sampler=self.sampler,
            buffer=self.buffer,
            source_fps_cap=self.source_fps_cap,
            max_frame_bytes=self.max_frame_bytes,
            on_input=self._on_source_frame,
            on_sampled=self._on_sampled_frame,
        )
        self.source = LiveCameraSource(ingestion=self.ingestion)
        self.webrtc = None
        self.simulation = None
        self.video_feeder = None
        self.camera_source = None
        self._last_persist_at = 0.0
        self._lock = threading.RLock()
        self._subscribers: List[_Subscriber] = []
        self._detection_subscribers: List[_Subscriber] = []
        self._frame_seq = 0
        self.detection = None
        self.detection_error: Optional[str] = None
        self.tracking = None
        self._tracking_subscribers: List[_Subscriber] = []
        self._tracking_frame_seq = 0
        self._preview_subscribers: List[_Subscriber] = []
        self.vlm_session = None
        self.vlm_error: Optional[str] = None
        self._vlm_subscribers: List[_Subscriber] = []
        self.evidence = None
        self.evidence_error: Optional[str] = None

    # -------------------------------------------------------------- state

    def publish(self, payload: dict) -> None:
        """Thread-safe broadcast to subscribed status consumers."""
        with self._lock:
            subs = list(self._subscribers)
        for sub in subs:
            loop = sub.loop
            if loop is None or loop.is_closed():
                continue
            try:
                loop.call_soon_threadsafe(_publish_item, payload, sub.queue)
            except RuntimeError:  # loop closed mid-flight
                continue

    def _publish(self, payload: dict) -> None:
        self.publish(payload)

    def publish_detection(self, payload: dict) -> None:
        """Thread-safe broadcast of a detection result to detection consumers."""
        with self._lock:
            subs = list(self._detection_subscribers)
        for sub in subs:
            loop = sub.loop
            if loop is None or loop.is_closed():
                continue
            try:
                loop.call_soon_threadsafe(_publish_item, payload, sub.queue)
            except RuntimeError:  # loop closed mid-flight
                continue
            except Exception:  # noqa: BLE001
                pass

    def _set_status(self, status: SessionStatus, error: Optional[str] = None) -> None:
        with self._lock:
            self.status = status
            self.error = error
            self.updated_at = _utcnow_iso()
            if status in (SessionStatus.COMPLETED, SessionStatus.ERROR, SessionStatus.DISCONNECTED):
                self.stopped_at = _utcnow_iso()
        if status in (SessionStatus.COMPLETED, SessionStatus.ERROR, SessionStatus.DISCONNECTED):
            self.stop_detection()
        self._persist()
        self._publish({"type": "status", "camera_id": self.camera_id, "session_id": self.session_db_id, "status": status.value, "transport": self.transport, "error": error, "updated_at": self.updated_at})

    # ------------------------------------------------------------ public

    def begin(self) -> None:
        """Move the session into CONNECTING (call after the DB row exists)."""
        if self.status in (SessionStatus.CREATED,):
            self._set_status(SessionStatus.CONNECTING)

    def transition(self, status: str, error: Optional[str] = None) -> None:
        self._set_status(SessionStatus(status), error=error)

    def mark_live(self) -> None:
        if self.status != SessionStatus.LIVE:
            self._set_status(SessionStatus.LIVE)
        self.start_detection()

    # --------------------------------------------------- detection lifecycle

    def start_detection(self) -> bool:
        """Start this session's YOLO worker (idempotent).

        Returns True when the worker is running. If detection is disabled or the
        model cannot be initialised the session stays LIVE - the reason is
        recorded in ``detection_error`` and surfaced in status. A model
        initialisation failure NEVER takes down an unrelated session.
        """
        if self.detection is not None and self.detection.running:
            return True
        from app.detection.pipeline import detection_enabled

        if not detection_enabled():
            self.detection_error = "Detection disabled by configuration"
            return False
        try:
            from app.detection.pipeline import DetectionPipeline

            pipeline = DetectionPipeline.build(
                on_result=self._on_detection_result,
                on_error=self._on_detection_error,
            )
        except Exception as exc:  # noqa: BLE001 - model init failure is per-session
            self.detection_error = f"Detection unavailable: {exc}"
            logger.warning(
                "Detection init failed (camera=%s): %s", self.camera_id, self.detection_error
            )
            self.detection = None
            self._persist()
            return False
        pipeline.start()
        self.detection = pipeline
        self.detection_error = None
        self.start_tracking()
        self.start_vlm()
        self.start_evidence()
        logger.info(
            "Detection pipeline started camera=%s transport=%s",
            self.camera_id,
            self.transport,
        )
        return True

    def stop_detection(self) -> None:
        if self.detection is None:
            self.stop_evidence()
            self.stop_vlm()
            return
        try:
            self.detection.stop(drain=False)
        except Exception:  # noqa: BLE001
            pass
        self.detection = None
        self.stop_tracking()
        self.stop_evidence()
        self.stop_vlm()

    def _on_detection_result(self, detection_frame) -> None:
        payload = detection_frame.as_broadcast()
        self.publish_detection(payload)
        if self.tracking is not None:
            self._feed_tracking(detection_frame)

    def _on_detection_error(self, exc: Exception) -> None:
        logger.warning("Detection worker error (camera=%s): %s", self.camera_id, exc)
        self.detection_error = str(exc)

    # --------------------------------------------- tracking lifecycle (Phase 3)

    def start_tracking(self) -> None:
        """Start the tracking pipeline for this session (idempotent)."""
        if self.tracking is not None:
            return
        if not getattr(settings, "TRACKING_ENABLED", True):
            return
        try:
            from app.tracking.pipeline import TrackingPipeline

            self.tracking = TrackingPipeline(
                session_id=str(self.session_db_id or ""),
                camera_id=str(self.camera_id),
                iou_threshold=getattr(settings, "TRACKING_IOU_THRESHOLD", 0.3),
                max_missing=getattr(settings, "TRACKING_MAX_MISSING", 30),
                max_tracks=getattr(settings, "TRACKING_MAX_TRACKS", 200),
                on_event=self._on_tracking_event,
            )
            logger.info("Tracking pipeline started camera=%s", self.camera_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tracking init failed (camera=%s): %s", self.camera_id, exc)
            self.tracking = None

    def _on_tracking_event(self, event) -> None:
        """Broadcast a tracking event and feed it to the VLM + evidence engines."""
        try:
            payload = event.as_broadcast() if hasattr(event, "as_broadcast") else event.model_dump()
            self.publish_tracking(payload)
        except Exception:  # noqa: BLE001
            pass
        if self.vlm_session is not None:
            try:
                self.vlm_session.on_event(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("VLM event feed failed (camera=%s): %s", self.camera_id, exc)
        if self.evidence is not None:
            try:
                self.evidence.on_event(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Evidence event capture failed (camera=%s): %s", self.camera_id, exc)

    def stop_tracking(self) -> None:
        if self.tracking is None:
            return
        try:
            self.tracking.stop()
        except Exception:  # noqa: BLE001
            pass
        self.tracking = None

    # ------------------------------------------------ VLM lifecycle (Phase 4)

    def start_vlm(self) -> None:
        """Start this session's VLM observation worker (idempotent)."""
        if self.vlm_session is not None and self.vlm_session.running:
            return
        if not getattr(settings, "VLM_ENABLED", True):
            self.vlm_error = "VLM disabled by configuration"
            return
        try:
            from app.vlm.session import VlmSession

            vlm = VlmSession(self)
            vlm.start()
            self.vlm_session = vlm
            self.vlm_error = None
            logger.info("VLM session started camera=%s", self.camera_id)
        except Exception as exc:  # noqa: BLE001 - per-session; never fatal
            self.vlm_session = None
            self.vlm_error = f"VLM unavailable: {exc}"
            logger.warning("VLM init failed (camera=%s): %s", self.camera_id, self.vlm_error)

    def stop_vlm(self) -> None:
        vlm = self.vlm_session
        self.vlm_session = None
        if vlm is not None:
            try:
                vlm.stop()
            except Exception:  # noqa: BLE001
                pass

    def publish_vlm(self, payload: dict) -> None:
        """Thread-safe broadcast of a VLM message to VLM consumers."""
        with self._lock:
            subs = list(self._vlm_subscribers)
        for sub in subs:
            loop = sub.loop
            if loop is None or loop.is_closed():
                continue
            try:
                loop.call_soon_threadsafe(_publish_item, payload, sub.queue)
            except RuntimeError:
                continue
            except Exception:  # noqa: BLE001
                pass
        # Durably capture any produced observation into evidence (Phase 5).
        if payload.get("type") == "vlm_observation" and self.evidence is not None:
            try:
                self.evidence.on_observation(payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Evidence observation capture failed (camera=%s): %s", self.camera_id, exc, exc_info=True)

    # -------------------------------------------------- evidence capture (Phase 5)

    def start_evidence(self) -> None:
        """Start this session's evidence capturer (idempotent)."""
        if self.evidence is not None:
            return
        if not getattr(settings, "EVIDENCE_ENABLED", True):
            self.evidence_error = "Evidence capture disabled by configuration"
            return
        try:
            from app.evidence.capture import EvidenceCapture

            cap = EvidenceCapture(self)
            cap.start()
            self.evidence = cap
            self.evidence_error = None
            logger.info("Evidence capture started camera=%s", self.camera_id)
        except Exception as exc:  # noqa: BLE001 - per-session; never fatal
            self.evidence = None
            self.evidence_error = f"Evidence capture unavailable: {exc}"
            logger.warning("Evidence capture init failed (camera=%s): %s", self.camera_id, self.evidence_error)

    def stop_evidence(self) -> None:
        cap = self.evidence
        self.evidence = None
        if cap is not None:
            try:
                cap.stop()
            except Exception:  # noqa: BLE001
                pass

    def evidence_snapshot(self) -> dict:
        if self.evidence is None:
            return {
                "evidence_enabled": False,
                "evidence_last_error": self.evidence_error,
                "evidence_captured": 0,
                "evidence_indexed": 0,
                "evidence_failed": 0,
            }
        snap = self.evidence.counts()
        if self.evidence_error and not snap.get("evidence_last_error"):
            snap["evidence_last_error"] = self.evidence_error
        return snap

    def subscribe_vlm(self) -> "_Subscriber":
        sub = _Subscriber()
        try:
            sub.loop = asyncio.get_running_loop()
        except RuntimeError:
            sub.loop = None
        with self._lock:
            self._vlm_subscribers.append(sub)
        return sub

    def unsubscribe_vlm(self, sub: "_Subscriber") -> None:
        with self._lock:
            if sub in self._vlm_subscribers:
                self._vlm_subscribers.remove(sub)

    def vlm_snapshot(self) -> dict:
        if self.vlm_session is None:
            return {
                "vlm_enabled": False,
                "vlm_last_error": self.vlm_error,
                "vlm_requests": 0,
                "vlm_observations": 0,
            }
        snap = self.vlm_session.snapshot()
        if self.vlm_error and not snap.get("vlm_last_error"):
            snap["vlm_last_error"] = self.vlm_error
        return snap

    def _feed_tracking(self, detection_frame) -> None:
        """Feed detection results into the tracking pipeline and broadcast.

        The tracker consumes plain dicts (``label``/``confidence``/``bbox``),
        while :class:`DetectionObject` uses ``class_name`` and a ``BoundingBox``
        model. Adapt across that seam here so downstream tracking never has to
        know about the detection schema.
        """
        try:
            detections = self._normalize_detections(getattr(detection_frame, "detections", []) or [])
            frame_index = getattr(detection_frame, "frame_id", None) or getattr(detection_frame, "frame_index", 0)
            ts = getattr(detection_frame, "frame_timestamp", None) or getattr(detection_frame, "timestamp", None)
            updates = self.tracking.update(detections, frame_index, ts)
            for u in updates:
                payload = u.as_broadcast() if hasattr(u, "as_broadcast") else u.model_dump() if hasattr(u, "model_dump") else {}
                self.publish_tracking(payload)
            snap = self.tracking.snapshot()
            if isinstance(snap, dict):
                self.publish_tracking({"type": "tracking_metrics", **snap})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tracking feed error (camera=%s): %s", self.camera_id, exc)

    @staticmethod
    def _normalize_detections(detections) -> list:
        """Coerce DetectionObject / dict detections to the tracker's dict form."""
        out = []
        for det in detections:
            if isinstance(det, dict):
                bbox = det.get("bbox")
                if hasattr(bbox, "x1"):
                    bbox = [bbox.x1, bbox.y1, bbox.x2, bbox.y2]
                elif bbox is not None:
                    bbox = list(bbox)
                out.append(
                    {
                        "label": det.get("label") or det.get("class_name") or "Person",
                        "confidence": det.get("confidence", 0.0),
                        "bbox": bbox,
                    }
                )
                continue
            bbox = getattr(det, "bbox", None)
            if hasattr(bbox, "x1"):
                bbox = [bbox.x1, bbox.y1, bbox.x2, bbox.y2]
            out.append(
                {
                    "label": getattr(det, "class_name", None) or getattr(det, "label", None) or "Person",
                    "confidence": float(getattr(det, "confidence", 0.0) or 0.0),
                    "bbox": bbox,
                }
            )
        return out

    def publish_tracking(self, payload: dict) -> None:
        """Thread-safe broadcast of a tracking result to tracking consumers."""
        with self._lock:
            subs = list(self._tracking_subscribers)
        for sub in subs:
            loop = sub.loop
            if loop is None or loop.is_closed():
                continue
            try:
                loop.call_soon_threadsafe(_publish_item, payload, sub.queue)
            except RuntimeError:
                continue
            except Exception:  # noqa: BLE001
                pass

    def subscribe_tracking(self) -> "_Subscriber":
        sub = _Subscriber()
        try:
            sub.loop = asyncio.get_running_loop()
        except RuntimeError:
            sub.loop = None
        with self._lock:
            self._tracking_subscribers.append(sub)
        return sub

    def unsubscribe_tracking(self, sub: "_Subscriber") -> None:
        with self._lock:
            if sub in self._tracking_subscribers:
                self._tracking_subscribers.remove(sub)

    def tracking_snapshot(self) -> dict:
        if self.tracking is None:
            return {"tracking_enabled": False, "active_tracks": 0, "total_events": 0}
        snap = self.tracking.snapshot()
        if isinstance(snap, dict):
            return {"tracking_enabled": True, **snap}
        return {"tracking_enabled": True, "active_tracks": 0}

    def _on_source_frame(self, frame, timestamp: float) -> None:
        if self.detection is not None:
            self.detection.metrics.record_input()

    def _on_sampled_frame(self, frame, timestamp: float, frame_id: int) -> None:
        if self.detection is None or not self.detection.running:
            return
        self.detection.metrics.record_sampled()
        with self._lock:
            self._frame_seq += 1
            seq = self._frame_seq
        self.detection.submit(
            frame,
            timestamp,
            frame_id=seq,
            session_id=self.session_db_id,
            camera_id=self.camera_id,
        )

    def stop(self) -> None:
        if self.status in (SessionStatus.COMPLETED, SessionStatus.ERROR, SessionStatus.DISCONNECTED):
            return
        self._set_status(SessionStatus.STOPPING)
        self._set_status(SessionStatus.COMPLETED)

    def mark_error(self, message: str) -> None:
        if self.status not in (SessionStatus.ERROR, SessionStatus.COMPLETED):
            self._set_status(SessionStatus.ERROR, error=message)
        else:
            self.error = message
            self._persist()

    def ingest_frame(self, frame, timestamp: Optional[float] = None) -> bool:
        """Thread-safe ingest entry point used by every transport."""
        with self._lock:
            if self.status not in SessionStatus.active_values():
                return False
            if self.source is None:
                return False
            ts = timestamp if timestamp is not None else time.time()
            accepted = self.source.push_with_ts(frame, ts)
            if accepted:
                self._bump_frame_counters()
                jpeg = self._encode_preview(frame)
                if jpeg is not None:
                    self.publish_preview(jpeg)
            return accepted

    def _bump_frame_counters(self) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_persist_at < 1.0:
                return
            self._last_persist_at = now
        self._persist()

    # --------------------------------------------------------- persistence

    def _persist(self) -> None:
        try:
            from app.database.session import SessionLocal

            db = SessionLocal()
            try:
                self._persist_sync(db)
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001 - persistence is best effort
            logger.warning("Live session persist failed (camera=%s): %s", self.camera_id, exc)

    def _persist_sync(self, db: Session) -> None:
        from app.database.models import Camera, CameraSession

        camera: Optional[Camera] = db.query(Camera).filter(Camera.id == self.camera_id).first()
        if camera is not None:
            camera.is_live = self.status in SessionStatus.active_values()
            camera.stream_status = self.status.value if self.status in SessionStatus.active_values() else "OFFLINE"

        if self.session_db_id is None:
            row = CameraSession(
                camera_id=self.camera_id,
                status=self.status.value,
                transport=self.transport,
                fps_target=self.fps_target,
                started_by_user_id=self.started_by_user_id,
                frames_received=self.ingestion.received,
                frames_sampled=self.ingestion.sampled,
                frames_buffered=self.buffer.count(),
                error=self.error,
                started_at=datetime.utcnow() if self.started_at else None,
                stopped_at=datetime.utcnow() if self.stopped_at else None,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            self.session_db_id = row.id
            self.updated_at = _utcnow_iso()
            return

        row: Optional[CameraSession] = db.query(CameraSession).filter(CameraSession.id == self.session_db_id).first()
        if row is None:
            self.session_db_id = None
            self._persist_sync(db)
            return
        counters = self._counters_sync()
        row.status = self.status.value
        row.transport = self.transport
        row.fps_target = self.fps_target
        row.error = self.error
        row.frames_received = counters["received"]
        row.frames_sampled = counters["sampled"]
        row.frames_buffered = self.buffer.count()
        row.latest_frame_at = datetime.utcnow()
        if self.stopped_at:
            row.stopped_at = datetime.utcnow()
        db.commit()

    def _counters_sync(self) -> dict:
        return {
            "received": self.ingestion.received,
            "sampled": self.ingestion.sampled,
        }

    # ------------------------------------------------------------ snapshot

    def snapshot(self) -> dict:
        with self._lock:
            status = self.status.value
            session_db_id = self.session_db_id
            error = self.error
            started_at = self.started_at
            stopped_at = self.stopped_at
            updated_at = self.updated_at
            detection_error = self.detection_error
        detection_metrics = (
            self.detection.snapshot() if self.detection is not None else None
        )
        if detection_metrics is not None:
            # Report the REAL loaded model/device (no GPU claim without evidence).
            try:
                if hasattr(self.detection, "model_info"):
                    detection_metrics = {**detection_metrics, **self.detection.model_info()}
            except Exception:  # noqa: BLE001 - metrics must never break status
                pass
        detection_recent = (
            len(self.detection.recent_results()) if self.detection is not None else 0
        )
        camera_source = getattr(self, "camera_source", None)
        source_health = self.source.health() if self.source is not None else None
        if camera_source is not None:
            source_health = camera_source.health()
        return {
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "session_id": session_db_id,
            "active": status in SessionStatus.active_values(),
            "status": status,
            "transport": self.transport,
            "source_health": source_health,
            "fps_target": self.fps_target,
            "window_seconds": self.window_seconds,
            "max_frames": self.max_frames,
            "frames_received": self.ingestion.received,
            "frames_sampled": self.ingestion.sampled,
            "frames_buffered": self.buffer.count(),
            "buffer_start": self.buffer.oldest_timestamp,
            "buffer_end": self.buffer.newest_timestamp,
            "started_by_user_id": self.started_by_user_id,
            "started_at": started_at,
            "stopped_at": stopped_at,
            "updated_at": updated_at,
            "error": error,
            "detection_enabled": self.detection is not None,
            "detection_error": detection_error,
            "detection_metrics": detection_metrics,
            "detection_recent_count": detection_recent,
            **self.tracking_snapshot(),
            **self.vlm_snapshot(),
            **self.evidence_snapshot(),
        }

    def decimated_count(self) -> int:
        return self.ingestion.decimated

    # --------------------------------------------------------- subscribers

    def subscribe(self) -> "_Subscriber":
        """Register a subscriber; call only from an event-loop thread.

        The subscriber captures the running loop so later ``publish()`` calls
        (from any thread) are scheduled safely on that loop.
        """
        sub = _Subscriber()
        try:
            sub.loop = asyncio.get_running_loop()
        except RuntimeError:  # no running loop -> publishing is a no-op
            sub.loop = None
        with self._lock:
            self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: "_Subscriber") -> None:
        with self._lock:
            if sub in self._subscribers:
                self._subscribers.remove(sub)

    def subscribe_detection(self) -> "_Subscriber":
        sub = _Subscriber()
        try:
            sub.loop = asyncio.get_running_loop()
        except RuntimeError:  # no running loop -> publishing is a no-op
            sub.loop = None
        with self._lock:
            self._detection_subscribers.append(sub)
        return sub

    def unsubscribe_detection(self, sub: "_Subscriber") -> None:
        with self._lock:
            if sub in self._detection_subscribers:
                self._detection_subscribers.remove(sub)

    def subscribe_preview(self) -> "_Subscriber":
        sub = _Subscriber()
        try:
            sub.loop = asyncio.get_running_loop()
        except RuntimeError:  # no running loop -> publishing is a no-op
            sub.loop = None
        with self._lock:
            self._preview_subscribers.append(sub)
        return sub

    def unsubscribe_preview(self, sub: "_Subscriber") -> None:
        with self._lock:
            if sub in self._preview_subscribers:
                self._preview_subscribers.remove(sub)

    def publish_preview(self, jpeg: bytes) -> None:
        """Thread-safe fan-out of an encoded frame to MJPEG consumers."""
        with self._lock:
            subs = list(self._preview_subscribers)
        for sub in subs:
            loop = sub.loop
            if loop is None or loop.is_closed():
                continue
            try:
                loop.call_soon_threadsafe(_publish_item, jpeg, sub.queue)
            except RuntimeError:  # loop closed mid-flight
                continue
            except Exception:  # noqa: BLE001
                pass

    def _encode_preview(self, frame) -> Optional[bytes]:
        """JPEG-encode a frame for the browser preview.

        Only runs when a preview subscriber exists, so a WebRTC session (which
        already delivers video natively) never pays for the encode.
        """
        with self._lock:
            wanted = bool(self._preview_subscribers)
        if not wanted or frame is None:
            return None
        try:
            import cv2

            ok, buf = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), int(settings.WEBCAM_PREVIEW_JPEG_QUALITY)],
            )
            if not ok:
                return None
            return buf.tobytes()
        except Exception as exc:  # noqa: BLE001 - preview must never break ingest
            logger.debug("Preview encode failed (camera=%s): %s", self.camera_id, exc)
            return None


class ActiveSessionError(RuntimeError):
    """A camera already has an active live session."""


class LiveCameraManager:
    """Singleton manager: at most one active session per camera."""

    def __init__(self) -> None:
        self._sessions: Dict[int, LiveSessionRuntime] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------- public

    def start(
        self,
        camera_id: int,
        camera_name: str,
        started_by_user_id: Optional[int],
        transport: str = "webrtc",
        **kwargs,
    ) -> LiveSessionRuntime:
        with self._lock:
            existing = self._sessions.get(camera_id)
            if existing is not None and existing.status in SessionStatus.active_values():
                raise ActiveSessionError(
                    f"Camera {camera_id} already has an active live session ({existing.status.value})"
                )
            runtime = LiveSessionRuntime(
                camera_id=camera_id,
                camera_name=camera_name,
                started_by_user_id=started_by_user_id,
                transport=transport,
                **kwargs,
            )
            self._sessions[camera_id] = runtime
            return runtime

    def get(self, camera_id: int) -> Optional[LiveSessionRuntime]:
        with self._lock:
            return self._sessions.get(camera_id)

    def stop(self, camera_id: int) -> Optional[LiveSessionRuntime]:
        with self._lock:
            runtime = self._sessions.get(camera_id)
        if runtime is None:
            return None
        runtime.stop()
        with self._lock:
            if self._sessions.get(camera_id) is runtime:
                del self._sessions[camera_id]
        return runtime

    def active_sessions(self) -> List[LiveSessionRuntime]:
        with self._lock:
            return [
                r
                for r in self._sessions.values()
                if r.status in SessionStatus.active_values()
            ]

    def snapshot_all(self) -> List[dict]:
        return [r.snapshot() for r in self.active_sessions()]

    def clear(self) -> None:
        with self._lock:
            runtimes = list(self._sessions.values())
            self._sessions.clear()
        for runtime in runtimes:
            runtime.stop_detection()
            simulation = getattr(runtime, "simulation", None)
            if simulation is not None:
                simulation.stop()
                runtime.simulation = None
            video_feeder = getattr(runtime, "video_feeder", None)
            if video_feeder is not None:
                video_feeder.stop()
                runtime.video_feeder = None
            camera_source = getattr(runtime, "camera_source", None)
            if camera_source is not None:
                try:
                    camera_source.stop()
                except Exception:  # noqa: BLE001
                    pass
                runtime.camera_source = None


manager = LiveCameraManager()