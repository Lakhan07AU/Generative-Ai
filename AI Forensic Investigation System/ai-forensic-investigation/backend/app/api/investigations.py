"""Agentic investigation API (Part 3).

Routes:
  POST /investigations                 - create an investigation workspace
  GET  /investigations                 - list investigations
  GET  /investigations/{id}            - detail (claims + timeline)
  POST /investigations/{id}/chat       - run the bounded investigation agent
  POST /investigations/{id}/claims     - create a claim manually
  POST /investigations/{id}/verify     - verify a claim (persist)
  GET  /investigations/{id}/timeline   - chronology
  GET  /investigations/{id}/audit      - audit trail for the investigation
  GET  /claims                         - list all claims
  GET  /claims/{id}                    - claim detail with verifications
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database import models
from app.schemas.investigation import (
    AgentAnswer,
    ChatRequest,
    ChatResponse,
    ClaimCreate,
    ClaimOut,
    InvestigationCreate,
    InvestigationDetail,
    InvestigationOut,
    TimelineEventOut,
    VerifyRequest,
    VerifyClaimResponse,
)
from app.auth.deps import get_current_user, require_roles
from app.audit.service import record_audit, log_verification
from app.verification.service import verify_claim

router = APIRouter(tags=["investigations"])


def _get_investigation_or_404(db: Session, investigation_id: int) -> models.Investigation:
    inv = db.query(models.Investigation).filter(models.Investigation.id == investigation_id).first()
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return inv


@router.post("/investigations", response_model=InvestigationOut, status_code=201)
def create_investigation(
    payload: InvestigationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    inv = models.Investigation(
        title=payload.title,
        description=payload.description,
        query=payload.query,
        video_id=payload.video_id,
        status="OPEN",
        created_by_user_id=current_user.id,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    record_audit(
        db, "investigation_created", user_id=current_user.id,
        entity_type="investigation", entity_id=inv.id,
        details=f"title={payload.title[:120]}",
    )
    return inv


@router.get("/investigations", response_model=list[InvestigationOut])
def list_investigations(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Investigation)
        .order_by(models.Investigation.created_at.desc())
        .limit(100)
        .all()
    )


@router.get("/investigations/{investigation_id}", response_model=InvestigationDetail)
def get_investigation(
    investigation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    inv = _get_investigation_or_404(db, investigation_id)
    return inv


@router.post("/investigations/{investigation_id}/chat", response_model=ChatResponse)
def investigation_chat(
    investigation_id: int,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    inv = _get_investigation_or_404(db, investigation_id)
    record_audit(
        db, "user_query", user_id=current_user.id,
        entity_type="investigation", entity_id=inv.id,
        details=f"message={payload.message[:200]}",
    )
    from app.agents.agent import run_investigation

    result = run_investigation(
        db,
        query=payload.message,
        investigation_id=inv.id,
        user_id=current_user.id,
        video_id=inv.video_id,
    )
    return ChatResponse(agent_result=AgentAnswer(**result))


@router.post("/investigations/{investigation_id}/claims", response_model=ClaimOut, status_code=201)
def create_claim(
    investigation_id: int,
    payload: ClaimCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    _: models.User = Depends(require_roles("INVESTIGATOR", "ADMIN")),
):
    _get_investigation_or_404(db, investigation_id)
    claim = models.Claim(
        investigation_id=investigation_id,
        claim_text=payload.claim_text,
        claim_type=payload.claim_type,
        status="OPEN",
    )
    db.add(claim)
    db.flush()
    for link in payload.evidence:
        db.add(models.ClaimEvidence(
            claim_id=claim.id,
            clip_id=link.clip_id,
            frame_id=link.frame_id,
            timestamp=link.timestamp,
            evidence_type=link.evidence_type,
            relevance_score=link.relevance_score,
        ))
    db.commit()
    db.refresh(claim)
    record_audit(
        db, "claim_created", user_id=current_user.id, entity_type="claim",
        entity_id=claim.id,
        details=f"investigation_id={investigation_id} type={payload.claim_type}",
    )
    return claim


@router.post("/investigations/{investigation_id}/verify", response_model=VerifyClaimResponse)
def verify_claim_endpoint(
    investigation_id: int,
    payload: VerifyRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _get_investigation_or_404(db, investigation_id)
    result = verify_claim(
        db,
        claim_text=payload.claim_text,
        investigation_id=payload.investigation_id,
        video_id=payload.video_id,
        timestamp=payload.timestamp,
        claim_type=payload.claim_type,
        persist=payload.persist,
    )
    if payload.persist and result.get("claim_id"):
        log_verification(db, investigation_id, current_user.id, result["claim_id"], result["result"])
    record_audit(
        db, "evidence_verification", user_id=current_user.id,
        entity_type="investigation", entity_id=investigation_id,
        details=f"result={result['result']} claim={payload.claim_text[:120]}",
    )
    return VerifyClaimResponse(
        id=result.get("claim_id", 0),
        claim_id=result.get("claim_id", 0),
        checks=result["checks"],
        result=result["result"],
        reason=result["reason"],
        verifier_version=result["verifier_version"],
    )


@router.get("/investigations/{investigation_id}/timeline", response_model=list[TimelineEventOut])
def get_timeline(
    investigation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _get_investigation_or_404(db, investigation_id)
    return (
        db.query(models.TimelineEvent)
        .filter(models.TimelineEvent.investigation_id == investigation_id)
        .order_by(models.TimelineEvent.timestamp.asc())
        .all()
    )


@router.get("/investigations/{investigation_id}/audit")
def get_investigation_audit(
    investigation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _get_investigation_or_404(db, investigation_id)
    rows = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.entity_type == "investigation",
            models.AuditLog.entity_id == investigation_id,
        )
        .order_by(models.AuditLog.created_at.asc())
        .limit(500)
        .all()
    )
    return [
        {
            "id": r.id,
            "action": r.action,
            "user_id": r.user_id,
            "details": r.details,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/claims", response_model=list[ClaimOut])
def list_claims(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Claim)
        .order_by(models.Claim.created_at.desc())
        .limit(200)
        .all()
    )


@router.get("/claims/{claim_id}", response_model=ClaimOut)
def get_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    claim = db.query(models.Claim).filter(models.Claim.id == claim_id).first()
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim
