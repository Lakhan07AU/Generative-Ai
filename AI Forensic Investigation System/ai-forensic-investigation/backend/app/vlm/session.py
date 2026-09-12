"""Per-session VLM orchestrator (Phase 4).

One :class:`VlmSession` per :class:`LiveSessionRuntime`. Owns the rate limiter,
the bounded worker queue/thread, metrics, and the recent-observation log. It
translates tracking events (and manual requests) into grounded observation
jobs; all broadcasts go through the runtime's publish path so WS clients and
status snapshots observe a single consistent stream.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Deque, List, Optional

from app.ai import provider
from app.core.config import settings
from app.live.rolling_buffer import RollingFrameBuffer
from app.tracking.schemas import TrackingEvent
from app.vlm.queue import VlmRateLimiter
from app.vlm.schemas import VlmMetrics, VlmObservation, VlmRequest, new_id
from app.vlm.selection import FrameSelection, select_for_event, select_latest
from app.vlm.worker import VlmJob, VlmWorker

logger = logging.getLogger(__name__)


def resolved_provider_mode() -> str:
    override = getattr(settings, "VLM_PROVIDER", "") or None
    mode = provider._resolve_mode(override)
    if mode != "simulation" and provider.available():
        return "openai"
    return "simulation"


def _frame_dims(frame_entry):
    shape = getattr(frame_entry.frame, "shape", None)
    if shape is not None and len(shape) >= 2:
        return int(shape[1]), int(shape[0])
    return 0, 0


class VlmSession:
    """Ties triggers, selection, rate limiting, the worker and broadcasting."""

    def __init__(self, runtime) -> None:
        self._runtime = runtime
        self._lock = threading.RLock()
        self._worker: Optional[VlmWorker] = None
        self._limiter = VlmRateLimiter(
            max_requests=getattr(settings, "VLM_MAX_REQUESTS_PER_SESSION", 60),
            cooldown_seconds=getattr(settings, "VLM_COOLDOWN_SECONDS", 30.0),
        )
        self._started = False
        self._stopped = False
        self._last_error: Optional[str] = None
        self._recent: Deque[VlmObservation] = deque(
            maxlen=int(getattr(settings, "VLM_RECENT_OBSERVATIONS", 5))
        )
        self._public_metrics = VlmMetrics()

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        with self._lock:
            if self._started or self._stopped:
                return
        worker = VlmWorker(on_publish=self._on_publish)
        self._worker = worker
        worker.start()
        self._started = True
        logger.info("VLM session started camera=%s", self._runtime.camera_id)

    def stop(self) -> None:
        with self._lock:
            worker = self._worker
            self._worker = None
            self._started = False
        if worker is not None:
            worker.stop()
        with self._lock:
            self._stopped = True

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._started and self._worker is not None and self._worker.running)

    # ------------------------------------------------------------- publish

    def _on_publish(self, payload: dict) -> None:
        if payload.get("type") == "vlm_observation":
            try:
                with self._lock:
                    self._recent.append(
                        VlmObservation.model_validate(payload)
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not cache observation: %s", exc)
        self._runtime.publish_vlm(payload)

    # ------------------------------------------------------------- triggers

    def on_event(self, event: TrackingEvent) -> None:
        """A tracking event fired - possibly enqueue an observation."""
        if not self.running:
            return
        from app.vlm.triggers import is_trigger_event

        if not is_trigger_event(event.event_type):
            return
        if not self._limiter.allow():
            self._record_dropped()
            return
        selection = select_for_event(
            self._runtime.buffer,
            event,
            max_frames=int(getattr(settings, "VLM_MAX_FRAMES_PER_REQUEST", 3)),
        )
        request = self._build_request(
            trigger="event",
            trigger_detail=event.event_type,
            selection=selection,
            event=event,
        )
        self._submit(request, selection)

    def manual_analyze(self) -> Optional[str]:
        """Manually request an observation of the current buffer.

        Returns the request id when accepted, else None (disabled / rate limited).
        """
        if not self.running:
            return None
        if not self._limiter.allow():
            self._record_dropped()
            return None
        selection = select_latest(
            self._runtime.buffer,
            max_frames=int(getattr(settings, "VLM_MAX_FRAMES_PER_REQUEST", 3)),
        )
        request = self._build_request(
            trigger="manual",
            trigger_detail="operator requested",
            selection=selection,
        )
        return self._submit(request, selection)

    # ------------------------------------------------------------- intern

    def _build_request(
        self,
        *,
        trigger: str,
        trigger_detail: Optional[str],
        selection: FrameSelection,
        event: Optional[TrackingEvent] = None,
    ) -> VlmRequest:
        from app.vlm.context import build_observe_context

        source_frames = [
            {
                "frame_id": f.sequence,
                "sequence": f.sequence,
                "timestamp": f.timestamp,
                "width": _frame_dims(f)[0],
                "height": _frame_dims(f)[1],
            }
            for f in selection.frames
        ]
        context = build_observe_context(
            self._runtime,
            camera_id=self._runtime.camera_id,
            camera_name=self._runtime.camera_name,
            session_id=self._runtime.session_db_id,
            trigger=trigger,
            trigger_detail=trigger_detail,
            source_frames=source_frames,
            window_start=selection.window_start,
            window_end=selection.window_end,
            event=event.model_dump(mode="json") if event is not None else None,
            provider_mode=resolved_provider_mode(),
        )
        return VlmRequest(
            request_id=new_id("req"),
            camera_id=self._runtime.camera_id,
            session_id=self._runtime.session_db_id,
            trigger=trigger,
            trigger_detail=trigger_detail,
            provider_mode=resolved_provider_mode(),
            context=context,
        )

    def _submit(self, request: VlmRequest, selection: FrameSelection) -> Optional[str]:
        worker = self._worker
        if worker is None:
            return None
        job = VlmJob(
            request=request,
            frames=[f for f in selection.frames],
            camera_name=self._runtime.camera_name,
            window_start=selection.window_start,
            window_end=selection.window_end,
        )
        accepted = worker.submit(job)
        if not accepted:
            self._record_dropped()
            return None
        self._public_metrics.total_requests += 1
        self._runtime.publish_vlm(request.as_broadcast())
        return request.request_id

    def _record_dropped(self) -> None:
        self._public_metrics.dropped_requests += 1
        logger.debug("Dropped VLM request (camera=%s)", self._runtime.camera_id)

    # ----------------------------------------------------------- snapshots

    def recent_observations(self, limit: Optional[int] = None) -> List[dict]:
        with self._lock:
            items = list(self._recent)
        if limit is not None:
            items = items[-limit:]
        return [o.as_broadcast() for o in items]

    def snapshot(self) -> dict:
        metrics = {
            "total_requests": self._public_metrics.total_requests,
            "total_observations": self._public_metrics.total_observations,
            "total_errors": self._public_metrics.total_errors,
            "dropped_requests": self._public_metrics.dropped_requests,
            "cooldown_active": self._limiter.cooldown_active(),
            "last_error": self._last_error,
        }
        worker = self._worker
        if worker is not None:
            w = worker.snapshot()
            metrics["total_observations"] = max(metrics["total_observations"], w.get("total_observations", 0))
            metrics["total_errors"] = max(metrics["total_errors"], w.get("total_errors", 0))
            metrics["last_error"] = w.get("last_error") or metrics["last_error"]
        return {
            "vlm_enabled": self.running,
            "vlm_last_error": None if not metrics["last_error"] else metrics["last_error"],
            "vlm_requests": metrics["total_requests"],
            "vlm_observations": metrics["total_observations"],
            "vlm_dropped": metrics["dropped_requests"],
            "vlm_cooldown_active": metrics["cooldown_active"],
        }

    def enabled(self) -> bool:
        return self.running