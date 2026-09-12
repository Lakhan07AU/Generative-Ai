"""Phase 7 - controlled investigation REST API.

Routes:
    POST /investigations/{investigation_id}/investigate   start + run + return
    GET  /investigations/{investigation_id}/runs         list runs for a case
    GET  /runs/{run_id}                                  run detail (audit view)
    POST /runs/{run_id}/review                           human review decision

RBAC:
    * starting / listing / reading runs requires a LIVE role
      (ADMIN / SECURITY_OFFICER / INVESTIGATOR); REVIEWER is denied.
    * reviewing (APPROVE / REJECT / CANCEL) additionally accepts the REVIEWER
      role - that is the human-review function of the system.

Every retrieval performed by a run is scoped to the investigation's camera(s),
so evidence from outside the case can never reach the agent.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.live import LIVE_ROLES
from app.audit.service import record_audit
from app.auth.deps import require_roles
from app.database import models
from app.database.models import Investigation, User
from app.database.session import get_db
from app.investigator import store
from app.investigator.agent import run_investigation
from app.investigator.camera_scope import case_camera_ids, case_camera_names
from app.investigator.schemas import ReviewRequest, RunStartRequest

router = APIRouter(tags=["investigator"])

RUN_REVIEW_ROLES = ("ADMIN", "SECURITY_OFFICER", "INVESTIGATOR", "REVIEWER")


def _run_or_404(db: Session, run_id: int) -> models.InvestigationRun:
    run = store.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Investigation run not found")
    return run


def _to_run_row(run: models.InvestigationRun) -> Dict[str, Any]:
    return {
        "id": run.id,
        "investigation_id": run.investigation_id,
        "status": run.status,
        "query": run.query,
        "metrics": store.loads_json(run.metrics, {}),
        "error": run.error,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }


@router.post("/investigations/{investigation_id}/investigate", response_model=Dict[str, Any])
def start_investigation_run(
    investigation_id: int,
    payload: RunStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    query = (payload.query or inv.query or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="No investigation query provided")

    camera_ids = case_camera_ids(db, inv.id)
    camera_names = case_camera_names(db, camera_ids)

    run = store.create_run(
        db,
        investigation_id=inv.id,
        user_id=current_user.id,
        query=query,
    )

    state = run_investigation(
        db,
        run_id=run.id,
        investigation_id=inv.id,
        query=query,
        camera_ids=camera_ids,
        camera_names=camera_names,
        user_id=current_user.id,
        require_review=payload.require_review,
    )

    record_audit(
        db,
        "investigation_run",
        user_id=current_user.id,
        entity_type="investigation",
        entity_id=inv.id,
        details=f"run_id={state.get('id')} status={state.get('status')} query={query[:120]}",
    )
    return state


@router.get("/investigations/{investigation_id}/runs")
def list_investigation_runs(
    investigation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    runs = store.list_runs(db, investigation_id)
    return {"runs": [_to_run_row(r) for r in runs]}


@router.get("/runs/{run_id}", response_model=Dict[str, Any])
def get_investigation_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    run = _run_or_404(db, run_id)
    return store.serialize_run(run)


@router.post("/runs/{run_id}/review", response_model=Dict[str, Any])
def review_investigation_run(
    run_id: int,
    payload: ReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*RUN_REVIEW_ROLES)),
):
    run = _run_or_404(db, run_id)
    if run.status != store.READY_FOR_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"Run is {run.status}; only READY_FOR_REVIEW runs can be reviewed",
        )
    if payload.decision == "APPROVE":
        store.set_status(db, run.id, store.COMPLETED)
    else:
        store.set_status(db, run.id, store.CANCELLED)

    note = payload.note or ""
    record_audit(
        db,
        "investigation_run_review",
        user_id=current_user.id,
        entity_type="investigation_run",
        entity_id=run.id,
        details=f"decision={payload.decision}{(' note=' + note) if note else ''}",
    )
    return store.serialize_run(run)