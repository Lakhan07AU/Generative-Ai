"""CCTV auto-processing supervisor (migration 0009 auto_process flag).

The supervisor is the background counterpart to manual live starts: for every
camera flagged ``auto_process=True`` with an RTSP URL it starts and keeps a live
``rtsp`` session - pulling the stream into the exact same ingest/detection/
tracking/evidence path as a manual session - and persists that camera's health
bookkeeping (``health_status``, ``last_seen_at``, ``last_error``,
``reconnect_attempts``) on every reconcile.

Behaviour contract:

* ``poll()`` is the single synchronisation point. It reconciles ALL desired
  state from the database in one pass; the background thread is only a timer
  that calls it.
* A camera with no active session is started (source constructed from its
  stream URL). A camera with an active session is left running and its health
  is refreshed from the live source.
* If the source's capture thread gives up (exhausted its internal restart
  budget - see :mod:`app.live.webcam_camera`) the session is torn down and the
  camera is NOT immediately cold-restarted: the ``min_restart_interval`` floor
  prevents a dead stream from hot-looping the service. The next poll past that
  floor starts it again (the source's own bounded restarts + backoff ride out
  brief outages without ever reaching this point).
* A camera that is no longer ``auto_process`` (flag cleared or row removed)
  has any supervisor-owned session stopped.
* Manual sessions on the same camera are never hijacked: an existing active
  session is left alone and simply adopted for health reporting.

Enabled/disabled and timings come from ``LIVE_AUTO_PROCESS_*`` settings so the
feature is inert by default and explicit at every deployment.
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

PERMITTED_HEALTH_STATES = ("OFFLINE", "CONNECTING", "ONLINE", "RECONNECTING", "ERROR")


def _app_session_factory():
    """Zero-arg callable returning a fresh DB session bound to the app engine."""
    from app.database.session import SessionLocal

    return SessionLocal


def default_source_factory(runtime, camera):
    """Build the RTSP source used for an auto-processed camera."""
    from app.live.rtsp_camera import RtspCameraSource

    stream_url = camera.rtsp_url or camera.rtsp_url_alt
    return RtspCameraSource(runtime, stream_url=stream_url)


class AutoProcessSupervisor:
    """Reconciles auto-process cameras with live RTSP sessions."""

    def __init__(
        self,
        manager,
        session_factory: Optional[Callable[[], object]] = None,
        source_factory: Optional[Callable] = None,
        enabled: Optional[bool] = None,
        poll_seconds: Optional[float] = None,
        min_restart_interval: Optional[float] = None,
        run_detection: Optional[bool] = None,
        clock=None,
    ) -> None:
        self._manager = manager
        self._session_factory = (
            session_factory
            if session_factory is not None
            else _app_session_factory()
        )
        self._source_factory = source_factory or default_source_factory
        self._enabled = settings.LIVE_AUTO_PROCESS_ENABLED if enabled is None else enabled
        self._poll_seconds = float(
            poll_seconds if poll_seconds is not None else settings.LIVE_AUTO_PROCESS_POLL_SECONDS
        )
        self._min_restart_interval = float(
            min_restart_interval
            if min_restart_interval is not None
            else settings.LIVE_AUTO_PROCESS_MIN_RESTART_INTERVAL_SECONDS
        )
        self._run_detection = bool(
            settings.LIVE_AUTO_PROCESS_DETECTION if run_detection is None else run_detection
        )
        self._clock = clock or time.time
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._owned: Dict[int, float] = {}  # camera_id -> last source end (epoch, 0=unknown)
        self._last_poll_at: Optional[float] = None

    # ------------------------------------------------------------- thread

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="live-auto-process-supervisor"
        )
        self._thread.start()
        logger.info(
            "auto-process supervisor started poll_seconds=%s min_restart_interval=%s detection=%s",
            self._poll_seconds,
            self._min_restart_interval,
            self._run_detection,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            if self._thread is not threading.current_thread():
                self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("auto-process supervisor stopped")

    def _run(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            try:
                self.poll()
            except Exception as exc:  # noqa: BLE001 - never kill the supervisor
                logger.error("auto-process reconcile failed: %s", exc)

    # ----------------------------------------------------------- reconcile

    def poll(self) -> dict:
        """One reconcile pass. Returns a summary dict (always, even on error)."""
        summary = {"scanned": 0, "started": 0, "kept": 0, "stopped": 0, "error": None}
        if not self._enabled:
            return summary
        db = self._session_factory()
        try:
            from app.database.models import Camera
            from app.live.manager import SessionStatus

            cameras = db.query(Camera).filter(Camera.auto_process.is_(True)).all()
            desired = {c.id for c in cameras}
            now = self._clock()
            for camera in cameras:
                summary["scanned"] += 1
                stream_url = (camera.rtsp_url or camera.rtsp_url_alt or "").strip()
                if not stream_url:
                    self._write_health(
                        db, camera, "OFFLINE", None, "no RTSP URL configured", 0
                    )
                    continue
                runtime = self._manager.get(camera.id)
                if runtime is None:
                    if self._skip_restart(camera.id, now):
                        self._write_health(
                            db,
                            camera,
                            "OFFLINE",
                            None,
                            "restarting; waiting for the restart interval floor",
                            self._restarts_for(camera),
                        )
                        continue
                    ok, error = self._start_camera(camera, stream_url)
                    if ok:
                        summary["started"] += 1
                        # Persist the just-started session's health on the same
                        # pass so status converges immediately.
                        self._adopt_for_health(db, camera, self._manager.get(camera.id))
                    else:
                        self._write_health(
                            db, camera, "ERROR", None, error or "failed to start RTSP session", 0
                        )
                    continue
                summary["kept"] += 1
                self._adopt_for_health(db, camera, runtime)
            # Stop supervisor-owned sessions whose flag was cleared.
            owned = self._owned.copy()
            for camera_id in owned:
                if camera_id in desired:
                    continue
                runtime = self._manager.get(camera_id)
                if runtime is not None:
                    self._manager.stop(camera_id)
                    summary["stopped"] += 1
                self._owned.pop(camera_id, None)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - reconcile must never crash
            summary["error"] = str(exc)
            logger.error("auto-process reconcile error: %s", exc)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        finally:
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass
        self._last_poll_at = self._clock()
        return summary

    # ------------------------------------------------------------- helpers

    def _start_camera(self, camera, stream_url: str):
        """Start a supervised session; returns ``(ok: bool, error: Optional[str])``."""
        from app.live.manager import ActiveSessionError

        try:
            runtime = self._manager.start(
                camera_id=camera.id,
                camera_name=camera.camera_name or "",
                started_by_user_id=None,
                transport="rtsp",
            )
        except ActiveSessionError:
            return False, None
        runtime.begin()
        if self._run_detection:
            runtime.start_detection()
        source = None
        try:
            source = self._source_factory(runtime, camera)
            source.on_finished = lambda: self._on_source_finished(runtime)
            source.start()
        except Exception as exc:  # noqa: BLE001 - stream refused, bad creds, etc.
            self._manager.stop(camera.id)
            logger.warning("auto-process camera=%s failed to start: %s", camera.id, exc)
            return False, str(exc)
        runtime.camera_source = source
        runtime.mark_live()
        self._owned.setdefault(camera.id, 0.0)
        logger.info(
            "auto-process camera=%s session started url=%s",
            camera.id,
            getattr(source, "_redact_url", lambda url: url)(stream_url),
        )
        return True, None

    def _on_source_finished(self, runtime) -> None:
        """A supervised capture thread gave up; tear down so poll can restart."""
        camera_id = runtime.camera_id
        with self._lock:
            self._owned[camera_id] = self._clock()
        try:
            self._manager.stop(camera_id)
        except Exception:  # noqa: BLE001
            pass

    def _skip_restart(self, camera_id: int, now: float) -> bool:
        with self._lock:
            ended_at = self._owned.get(camera_id)
        if ended_at is None or ended_at <= 0:
            return False
        return (now - ended_at) < self._min_restart_interval

    def _restarts_for(self, camera) -> int:
        runtime = self._manager.get(camera.id)
        if runtime is not None:
            source = getattr(runtime, "camera_source", None)
            restarts = getattr(source, "_restarts", None) if source is not None else None
            if restarts is not None:
                return int(restarts)
        data = getattr(camera, "reconnect_attempts", None)
        return int(data or 0)

    def _adopt_for_health(self, db, camera, runtime) -> None:
        """Refresh camera health bookkeeping from the live supervised source."""
        source = getattr(runtime, "camera_source", None)
        if source is None:
            self._write_health(
                db, camera, "ERROR", None, runtime.error or "session without a source", 0
            )
            return
        try:
            info = source.health()
        except Exception:  # noqa: BLE001
            info = {}
        alive = bool(info.get("alive", False))
        running = bool(info.get("running", False))
        opened = bool(info.get("opened", False))
        error = (info.get("error") or None) or (runtime.error or None)
        restarts = int(info.get("restarts", 0))
        if running and not alive:
            state = "RECONNECTING"
        elif alive and opened:
            state = "ONLINE"
        else:
            state = "OFFLINE"
        last_frame = info.get("last_frame_at")
        self._write_health(
            db, camera, state, last_frame, error, restarts
        )

    def _write_health(self, db, camera, state, last_frame_at, error, restarts) -> None:
        try:
            camera.health_status = state if state in PERMITTED_HEALTH_STATES else "OFFLINE"
            if last_frame_at:
                camera.last_seen_at = datetime.utcfromtimestamp(float(last_frame_at))
            camera.last_error = error if error else None
            camera.reconnect_attempts = int(restarts or 0)
            db.add(camera)
        except Exception as exc:  # noqa: BLE001 - health write is best effort
            logger.warning("auto-process health write failed (camera=%s): %s", camera.id, exc)


_supervisor: Optional[AutoProcessSupervisor] = None


def get_auto_process_supervisor():
    """Lazily construct the process-wide supervisor singleton."""
    global _supervisor
    if _supervisor is None:
        from app.live.manager import manager

        _supervisor = AutoProcessSupervisor(manager)
    return _supervisor


def start_supervisor_if_enabled() -> None:
    supervisor = get_auto_process_supervisor()
    if supervisor._enabled:
        supervisor.start()


def stop_supervisor() -> None:
    global _supervisor
    if _supervisor is not None:
        _supervisor.stop()
        _supervisor = None


__all__ = ["AutoProcessSupervisor", "get_auto_process_supervisor", "start_supervisor_if_enabled", "stop_supervisor"]