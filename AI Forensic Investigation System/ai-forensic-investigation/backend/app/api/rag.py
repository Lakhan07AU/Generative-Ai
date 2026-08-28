"""RAG + Findings API (Part 2).

Routes:
  POST /rag/query           - Video RAG natural-language investigation
  POST /rag/policy-question - Policy assessment of a question + video evidence
  GET  /findings             - List persisted findings
  POST /findings/{id}/resolve - (reserved) - not implemented
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database import models
from app.schemas.rag import (
    RAGQueryRequest,
    RAGQueryResponse,
    PolicyQuestionRequest,
    PolicyQuestionResponse,
    FindingOut,
)
from app.auth.deps import get_current_user
from app.rag.video_rag import video_rag_answer
from app.rag.policy_rag import policy_question as policy_question_fn
from app.audit.service import record_audit

router = APIRouter(tags=["rag"])


@router.post("/rag/query", response_model=RAGQueryResponse)
def rag_query(
    payload: RAGQueryRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    filters = {}
    if payload.video_id:
        filters["video_id"] = payload.video_id
    if payload.camera_id:
        filters["camera_id"] = payload.camera_id
    result = video_rag_answer(db, payload.query, filters)
    _persist_findings(
        db,
        current_user,
        payload.query,
        result,
        finding_type="video_rag",
        status_field="status",
    )
    record_audit(
        db, "rag_query", user_id=current_user.id, entity_type="rag",
        entity_id=None, details=f"status={result['status']} query={payload.query[:120]}",
    )
    return result


@router.post("/rag/policy-question", response_model=PolicyQuestionResponse)
def policy_question_endpoint(
    payload: PolicyQuestionRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    result = policy_question_fn(db, payload.question, payload.video_id)
    if result["status"] != "UNKNOWN":
        row = models.Finding(
            video_id=result.get("video_id"),
            clip_id=result.get("clip_id"),
            finding_status=result["status"],
            finding_type="policy_assessment",
            question=payload.question,
            description=result["description"],
            confidence=0.9 if result["status"] == "POLICY-ASSESSED" else 0.5,
            policy_id=result.get("policy_id"),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        result["finding_id"] = row.id
    record_audit(
        db, "policy_question", user_id=current_user.id, entity_type="policy_assessment",
        entity_id=None, details=f"status={result['status']} question={payload.question[:120]}",
    )
    return result


@router.get("/findings", response_model=list[FindingOut])
def list_findings(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Finding)
        .order_by(models.Finding.created_at.desc())
        .limit(100)
        .all()
    )


def _persist_findings(db, user, question, result, finding_type: str, status_field: str):
    from app.schemas.rag import EvidenceCard

    evidence = result.get("evidence", [])
    verified = [e for e in evidence if (e.get("verification") or {}).get("verified")]
    status = result.get(status_field)
    row = models.Finding(
        video_id=verified[0]["video_id"] if verified else None,
        clip_id=verified[0]["clip_id"] if verified else None,
        finding_status="VERIFIED" if verified else ("UNKNOWN" if status == "UNKNOWN" else "OBSERVED"),
        finding_type=finding_type,
        question=question,
        description=result.get("answer") or result.get("description"),
        confidence=0.9 if verified else 0.2,
        retrieval_score=verified[0]["retrieval_score"] if verified else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
