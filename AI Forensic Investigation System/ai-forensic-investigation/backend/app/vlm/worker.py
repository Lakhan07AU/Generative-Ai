"""Per-session threaded VLM worker (Phase 4).

Mirrors the detection worker's design: ONE session owns ONE bounded queue and
ONE consumer thread, so cameras never share VLM queue/state. The provider call
(HTTP in real mode) runs on the working thread so FastAPI's event loop is
never blocked. Queue policy: when full the OLDEST pending request is evicted
(we prefer the freshest evidence); evictions are counted. Transient provider
failures retry with backoff; a final failure publishes a ``vlm_error`` message
and the worker keeps running - a VLM problem never kills the live session.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, List, Optional

from app.ai import provider
from app.core.config import settings
from app.vlm.schemas import (
    VlmMetrics,
    VlmObservation,
    VlmRequest,
    VlmSourceFrame,
    build_observation,
    utcnow_iso,
)
from app.vlm.preprocess import PreparedFrame, encode_frames

logger = logging.getLogger(__name__)

PublishCallback = Callable[[dict], None]


@dataclass
class VlmJob:
    request: VlmRequest
    frames: List[object] = field(default_factory=list)
    camera_name: Optional[str] = None
    window_start: Optional[float] = None
    window_end: Optional[float] = None


class VlmWorker:
    """One session's asynchronous observation producer/consumer."""

    def __init__(
        self,
        on_publish: PublishCallback,
        maxsize: Optional[int] = None,
        retries: Optional[int] = None,
        backoff_seconds: Optional[float] = None,
        clock=None,
    ) -> None:
        self._on_publish = on_publish or (lambda _d: None)
        self._maxsize = max(1, int(maxsize if maxsize is not None else settings.VLM_MAX_QUEUE))
        self._retries = int(retries if retries is not None else settings.VLM_RETRIES)
        self._backoff = float(backoff_seconds if backoff_seconds is not None else settings.VLM_RETRY_BACKOFF_SECONDS)
        self._clock = clock or time.monotonic

        self._queue: Deque[VlmJob] = deque()
        self._lock = threading.Condition(threading.Lock())
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._metrics = VlmMetrics()
        self.camera_id: int = 0

    # -------------------------------------------------------------- control

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="vlm-worker",
            daemon=True,
        )
        self._thread.start()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    def submit(self, job: VlmJob) -> bool:
        """Queue an observation job (evict oldest when full).

        Returns True when accepted (possibly after eviction), False when the
        worker is not running.
        """
        if not self.running:
            return False
        with self._lock:
            if len(self._queue) >= self._maxsize:
                self._queue.popleft()
                self._metrics.dropped_requests += 1
            self._queue.append(job)
            self._lock.notify()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """Signal stop and join the thread (never blocks more than timeout)."""
        self._stop.set()
        with self._lock:
            self._queue.clear()
            self._lock.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def snapshot(self) -> dict:
        with self._lock:
            return self._metrics.as_broadcast()

    # ----------------------------------------------------------------- run

    def _run(self) -> None:
        while not self._stop.is_set():
            job: Optional[VlmJob] = None
            with self._lock:
                while not self._queue and not self._stop.is_set():
                    self._lock.wait(timeout=1.0)
                if self._queue:
                    job = self._queue.popleft()
            if job is None:
                continue
            try:
                self._process(job)
            except Exception as exc:  # noqa: BLE001 - worker must never die
                logger.warning("VLM worker error (req=%s): %s", job.request.request_id, exc)
                self._metrics.total_errors += 1
                self._metrics.last_error = str(exc)
                self._emit_error(str(exc), job.request.request_id, job.request.camera_id)

    def _emit_error(self, detail: str, request_id: str, camera_id: int) -> None:
        self._on_publish(
            {
                "type": "vlm_error",
                "camera_id": camera_id,
                "request_id": request_id,
                "detail": detail,
                "at": utcnow_iso(),
            }
        )

    def _process(self, job: VlmJob) -> None:
        started = self._clock()
        self.camera_id = job.request.camera_id
        try:
            prepared, dropped = encode_frames(
                job.frames,
                max_side=getattr(settings, "VLM_MAX_IMAGE_SIDE", 1280),
                jpeg_quality=getattr(settings, "VLM_JPEG_QUALITY", 80),
                max_bytes=getattr(settings, "VLM_MAX_IMAGE_BYTES", 512 * 1024),
            )
            if dropped:
                logger.debug("vlm preprocess dropped %s frame(s) for %s", dropped, job.request.request_id)
        except Exception as exc:  # noqa: BLE001
            self._metrics.total_errors += 1
            self._metrics.last_error = f"preprocess failed: {exc}"
            self._emit_error(self._metrics.last_error, job.request.request_id, job.request.camera_id)
            return

        if not prepared:
            result = {
                "summary": "[SIMULATED VLM] No usable frames could be encoded for vision analysis.",
                "statements": [
                    {
                        "statement": "No usable frames were available in the requested window; visual content could not be verified.",
                        "classification": "UNKNOWN",
                        "confidence": 0.0,
                        "basis": [],
                    }
                ],
                "notes": ["No evidence frames could be encoded for the vision provider."],
                "model": "no-op",
            }
        else:
            observe_context = {
                **job.request.context,
                "source_frames": [
                    {
                        "frame_id": p.frame_id,
                        "sequence": p.sequence,
                        "timestamp": p.timestamp,
                        "width": p.width,
                        "height": p.height,
                    }
                    for p in prepared
                ],
            }
            result = self._call_provider(prepared, observe_context, job.request.request_id)
            if result is None:
                return  # error already emitted

        source_frames = [
            VlmSourceFrame(
                frame_id=p.frame_id,
                sequence=p.sequence,
                timestamp=p.timestamp,
                width=p.width,
                height=p.height,
            )
            for p in prepared
        ]
        observation = build_observation(
            job.request,
            result,
            source_frames,
            job.window_start,
            job.window_end,
            camera_name=job.camera_name,
        )
        self._record_success(observation, started)
        self._on_publish(observation.as_broadcast())

    def _call_provider(
        self,
        prepared: List[PreparedFrame],
        observe_context: dict,
        request_id: str,
    ) -> Optional[dict]:
        frames = [
            {
                "data": p.data,
                "frame_id": p.frame_id,
                "sequence": p.sequence,
                "timestamp": p.timestamp,
                "width": p.width,
                "height": p.height,
            }
            for p in prepared
        ]
        last_exc: Optional[Exception] = None
        for attempt in range(self._retries + 1):
            if self._stop.is_set():
                return None
            try:
                override = getattr(settings, "VLM_PROVIDER", "") or None
                return provider.vision_observe_frames(
                    frames, observe_context, provider_override=override
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self._metrics.total_retries += 1
                logger.warning(
                    "VLM observation attempt %s/%s failed (req=%s): %s",
                    attempt + 1,
                    self._retries + 1,
                    request_id,
                    exc,
                )
                if attempt < self._retries:
                    time.sleep(self._backoff * (attempt + 1))
        self._metrics.total_errors += 1
        self._metrics.last_error = str(last_exc)
        self._emit_error(str(last_exc), request_id, self.camera_id)
        return None

    def _record_success(self, observation: VlmObservation, started: float) -> None:
        latency = (self._clock() - started) * 1000.0
        self._metrics.total_observations += 1
        self._metrics.last_observation_at = utcnow_iso()
        avg = self._metrics.avg_latency_ms
        n = self._metrics.total_observations - 1
        self._metrics.avg_latency_ms = avg + (latency - avg) / n if n else latency
        self._metrics.max_latency_ms = max(self._metrics.max_latency_ms, latency)