"""Phase 6 investigation search API.

Route:
    POST /investigation/search

Turns a natural-language investigator question into a grounded answer over the
forensic evidence of a specific investigation (``case_id``). RBAC: any LIVE role
(ADMIN / SECURITY_OFFICER / INVESTIGATOR); REVIEWER is denied. The camera scope
is derived from the investigation's bound video, so evidence from cameras
outside the case can never leak into the answer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.live import LIVE_ROLES
from app.audit.service import record_audit
from app.auth.deps import require_roles
from app.database import models
from app.database.models import Investigation, User
from app.database.session import get_db
from app.investigation import build_answer, parse_query, rerank_candidates, retrieve_investigation_evidence
from app.investigation.retrieval import camera_names
from app.investigation.schemas import InvestigationSearchRequest, InvestigationSearchResponse

router = APIRouter(tags=["investigation-search"])


def _case_camera_ids(db: Session, investigation_id: int) -> list[int]:
    inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
    if inv is None or inv.video_id is None:
        return []
    video = db.query(models.Video).filter(models.Video.id == inv.video_id).first()
    if video is None or video.camera_id is None:
        return []
    return [int(video.camera_id)]


@router.post("/investigation/search", response_model=InvestigationSearchResponse)
def investigation_search(
    payload: InvestigationSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LIVE_ROLES)),
):
    inv = db.query(Investigation).filter(Investigation.id == payload.case_id).first()
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    camera_ids = _case_camera_ids(db, inv.id)
    parsed = parse_query(payload.query)
    top_k = payload.top_k
    candidates = retrieve_investigation_evidence(db, payload.query, parsed, camera_ids, limit=top_k)
    ranked = rerank_candidates(candidates, parsed)
    names = camera_names(db, camera_ids)
    response = build_answer(payload.query, parsed, ranked, camera_ids, names)

    record_audit(
        db,
        "investigation_search",
        user_id=current_user.id,
        entity_type="investigation",
        entity_id=inv.id,
        details=f"query={payload.query[:200]} status={response['status']}",
    )
    return response