"""Audit log listing API (Phase 9).

Routes:
  GET /audit/logs - paginated audit log entries (ADMIN)
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database import models
from app.auth.deps import require_roles

router = APIRouter(prefix="/audit", tags=["audit"])

AUDIT_FILTER_ACTIONS = {
    "user_register",
    "user_login",
    "user_logout",
    "live_session_start",
    "live_session_stop",
    "vlm_analysis",
    "investigation_run",
    "investigation_review",
    "report_generation",
    "report_review",
}


@router.get("/logs")
def list_audit_logs(
    action: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("ADMIN")),
):
    query = db.query(models.AuditLog)
    if action:
        if action not in AUDIT_FILTER_ACTIONS:
            action = action.strip().lower()
        query = query.filter(models.AuditLog.action == action)
    rows = query.order_by(models.AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "user_id": r.user_id,
            "user_email": r.user.email if r.user else None,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "details": r.details,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/actions")
def list_audit_actions(
    _: models.User = Depends(require_roles("ADMIN")),
):
    return sorted(AUDIT_FILTER_ACTIONS)