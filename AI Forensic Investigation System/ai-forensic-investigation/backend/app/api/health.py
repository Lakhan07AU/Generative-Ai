"""Health + metrics endpoints (Phase 9 operational observability).

``GET /health``  - detailed per-component status (database, vector store,
storage backend, evidence indexer, live sessions). Kept probe-friendly: the top
level ``status`` is ``"ok"`` only when every checked component reports ok.

``GET /metrics`` - dependency-free Prometheus-style text exposition of the few
counters the backend already tracks (evidence indexer, live frames, sessions,
vector points). Enough to wire into a cheap collector without new dependencies.
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.session import get_db

router = APIRouter(tags=["health"])


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.get("/health")
def health(db: Session = Depends(get_db)):
    components = {}

    try:
        db.execute(text("SELECT 1"))
        components["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        components["database"] = {"ok": False, "error": str(exc)[:300]}

    from app.ai.qdrant_service import qdrant
    components["qdrant"] = qdrant.health()

    from app.storage.service import storage
    storage_health = storage.health()
    components["storage"] = storage_health

    from app.evidence.indexer import evidence_indexer
    components["evidence_indexer"] = {
        "ok": True,
        "running": evidence_indexer.running,
        **evidence_indexer.snapshot(),
    }

    from app.live.manager import manager
    components["live"] = {
        "ok": True,
        "active_sessions": len(manager.active_sessions()),
        "transports": _live_transports(manager),
    }

    # Every component that reports an explicit "ok" must agree.
    checked = {
        name: value
        for name, value in components.items()
        if isinstance(value, dict) and "ok" in value
    }
    ok = bool(checked) and all(v["ok"] for v in checked.values())

    return {
        "status": "ok" if ok else "degraded",
        "service": "ai-forensic-investigation",
        "version": "1.0.0",
        "time": _utcnow_iso(),
        "components": components,
    }


def _live_transports(manager) -> list:
    try:
        return [
            {"camera_id": r.camera_id, "transport": r.transport, "status": r.status.value}
            for r in manager.active_sessions()
        ]
    except Exception:  # noqa: BLE001
        return []


@router.get("/metrics", response_class=PlainTextResponse)
def metrics():
    from app.ai.qdrant_service import qdrant
    from app.evidence.indexer import evidence_indexer
    from app.live.manager import manager
    from app.storage.service import storage

    indexer = evidence_indexer.snapshot()
    lines = [
        "# HELP forensics_engine_up Whether the API process is serving.",
        "# TYPE forensics_engine_up gauge",
        "forensics_engine_up 1",
        "",
        "# HELP forensics_vector_backend_specific name of the active vector store.",
        "# TYPE forensics_vector_backend_specific gauge",
        "forensics_vector_backend_specific{" + f"backend=\"{qdrant.backend_name()}\"" + "} 1",
        "",
        "# HELP forensics_storage_backend_specific name of the active object store.",
        "# TYPE forensics_storage_backend_specific gauge",
        "forensics_storage_backend_specific{" + f"backend=\"{storage.backend_name()}\"" + "} 1",
        "",
        "# HELP forensics_evidence_indexer_bytes counters of the indexing worker.",
        "# TYPE forensics_evidence_indexer_bytes gauge",
        f"forensics_evidence_indexer_queue_size {indexer['queue_size']}",
        f"forensics_evidence_indexer_total_indexed {indexer['total_indexed']}",
        f"forensics_evidence_indexer_total_failed {indexer['total_failed']}",
        f"forensics_evidence_indexer_total_dropped {indexer['total_dropped']}",
        "",
        "# HELP forensics_live_active_sessions Number of live sessions in memory.",
        "# TYPE forensics_live_active_sessions gauge",
        f"forensics_live_active_sessions {len(manager.active_sessions())}",
        "",
        "# HELP forensics_live_source_frames Frames pushed / dropped by live sources.",
        "# TYPE forensics_live_source_frames gauge",
    ]
    pushed = 0
    dropped = 0
    for r in manager.active_sessions():
        try:
            pushed += r.source.pushed if r.source is not None else 0
            dropped += r.source.dropped if r.source is not None else 0
        except Exception:  # noqa: BLE001
            pass
    lines.append(f"forensics_live_source_frames_pushed_total {pushed}")
    lines.append(f"forensics_live_source_frames_dropped_total {dropped}")
    lines.append(f"# HELP forensics_uptime_seconds Uptime of this process.")
    lines.append("# TYPE forensics_uptime_seconds gauge")
    lines.append(f"forensics_uptime_seconds {int(time.monotonic())}")
    return "\n".join(lines) + "\n"


__all__ = ["router"]