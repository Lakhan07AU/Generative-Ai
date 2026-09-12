"""Phase 7 - run persistence, status machine and checkpoints.

Every Phase 7 run is persisted to ``investigation_runs`` and checkpointed at
every node boundary so the front-end can poll status + step history mid-run and
humans can audit exactly what the agent did, in what order, and within which
bounds. Reviewable findings also materialise as shared Part 3 workspace rows
(Claim / Verification / TimelineEvent) so the existing investigation UI can
render them.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.database import models

# Status machine (Phase 7).
CREATED = "CREATED"
PLANNING = "PLANNING"
RETRIEVING = "RETRIEVING"
ANALYZING = "ANALYZING"
VERIFYING = "VERIFYING"
BUILDING_TIMELINE = "BUILDING_TIMELINE"
READY_FOR_REVIEW = "READY_FOR_REVIEW"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

RUN_STATUS_FLOW = (
    CREATED,
    PLANNING,
    RETRIEVING,
    ANALYZING,
    VERIFYING,
    BUILDING_TIMELINE,
    READY_FOR_REVIEW,
    COMPLETED,
    FAILED,
    CANCELLED,
)

TERMINAL = (COMPLETED, FAILED, CANCELLED)

_VALID_TRANSITION = {
    CREATED: {PLANNING, FAILED, CANCELLED},
    # Unanswerable runs skip retrieval: PLANNING -> COMPLETED / READY_FOR_REVIEW.
    PLANNING: {RETRIEVING, ANALYZING, COMPLETED, READY_FOR_REVIEW, FAILED, CANCELLED},
    RETRIEVING: {ANALYZING, FAILED, CANCELLED},
    ANALYZING: {VERIFYING, FAILED, CANCELLED},
    # Expansion loops: VERIFYING -> ANALYZING for another bounded pass.
    VERIFYING: {BUILDING_TIMELINE, ANALYZING, FAILED, CANCELLED},
    BUILDING_TIMELINE: {READY_FOR_REVIEW, COMPLETED, FAILED, CANCELLED},
    READY_FOR_REVIEW: {COMPLETED, CANCELLED},
    COMPLETED: set(),
    FAILED: set(),
    CANCELLED: set(),
}


def _now() -> datetime:
    return datetime.utcnow()


def _dumps(obj: Any) -> Optional[str]:
    return json.dumps(obj) if obj is not None else None


def loads_json(text: Optional[str], default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_run(
    db,
    *,
    investigation_id: int,
    user_id: Optional[int],
    query: str,
) -> models.InvestigationRun:
    run = models.InvestigationRun(
        investigation_id=investigation_id,
        status=CREATED,
        query=(query or "").strip(),
        created_by_user_id=user_id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run(db, run_id: int) -> Optional[models.InvestigationRun]:
    return db.query(models.InvestigationRun).filter(models.InvestigationRun.id == run_id).first()


def list_runs(db, investigation_id: int, limit: int = 50) -> List[models.InvestigationRun]:
    return (
        db.query(models.InvestigationRun)
        .filter(models.InvestigationRun.investigation_id == investigation_id)
        .order_by(models.InvestigationRun.created_at.desc())
        .limit(int(limit))
        .all()
    )


def set_status(db, run_id: int, status: str, error: Optional[str] = None) -> None:
    run = get_run(db, run_id)
    if run is None:
        return
    if run.status == status:
        # Re-entering the same node (e.g. expansion loop analyse->analyse) is a
        # no-op, not a transition.
        return
    allowed = _VALID_TRANSITION.get(run.status, set())
    if status not in allowed:
        raise ValueError(
            f"invalid run status transition {run.status!r} -> {status!r}"
        )
    old = run.status
    run.status = status
    if error:
        run.error = error
    if status == PLANNING and run.started_at is None:
        run.started_at = _now()
    if status in TERMINAL:
        run.completed_at = _now()
    db.commit()
    db.refresh(run)


def checkpoint(
    db,
    run_id: int,
    *,
    classification: Optional[Dict[str, Any]] = None,
    plan: Optional[List[Dict[str, Any]]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    claims: Optional[List[Dict[str, Any]]] = None,
    result: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist a node-boundary snapshot of the run state."""
    run = get_run(db, run_id)
    if run is None:
        return
    if classification is not None:
        run.classification = _dumps(classification)
    if plan is not None:
        run.plan = _dumps(plan)
    if steps is not None:
        run.steps = _dumps(steps)
    if claims is not None:
        run.claims = _dumps(claims)
    if result is not None:
        run.result = _dumps(result)
    if metrics is not None:
        run.metrics = _dumps(metrics)
    db.commit()
    db.refresh(run)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_run(run: models.InvestigationRun) -> Dict[str, Any]:
    return {
        "id": run.id,
        "investigation_id": run.investigation_id,
        "status": run.status,
        "query": run.query,
        "classification": loads_json(run.classification, {}),
        "plan": loads_json(run.plan, []),
        "steps": loads_json(run.steps, []),
        "claims": loads_json(run.claims, []),
        "result": loads_json(run.result, {}),
        "metrics": loads_json(run.metrics, {}),
        "error": run.error,
        "created_by_user_id": run.created_by_user_id,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }


# ---------------------------------------------------------------------------
# Workspace materialization (shared Part 3 models)
# ---------------------------------------------------------------------------


def persist_workspace(
    db,
    run_id: int,
    *,
    claims_internal: List[Dict[str, Any]],
    timeline: List[Dict[str, Any]],
) -> None:
    """Materialize run claims (with verification) and timeline as workspace rows.

    Uses the shared Claim / Verification / ClaimEvidence / TimelineEvent models
    so Phase 7 output shows up in the existing investigation UI and audit trail.
    Verified, conflict-free claims become Claim rows; conflicts mark claims
    PARTIALLY_VERIFIED; timeline entries become TimelineEvent rows.
    """
    run = get_run(db, run_id)
    if run is None:
        return
    inv_id = run.investigation_id

    for f in claims_internal:
        result = f.get("verification", {}).get("result", "INSUFFICIENT_EVIDENCE")
        claim = models.Claim(
            investigation_id=inv_id,
            claim_text=f.get("text", "")[:1000],
            claim_type=f.get("claim_type", "OBSERVATION"),
            status=result if result != "CONFLICTED" else "PARTIALLY_VERIFIED",
            confidence=f.get("confidence"),
        )
        db.add(claim)
        db.flush()
        evidence_ids = [e.get("evidence_id") for e in f.get("evidence", []) if e.get("evidence_id")]
        db.add(
            models.Verification(
                claim_id=claim.id,
                checks=json.dumps(
                    {
                        "evidence_ids": evidence_ids,
                        "conflicts": f.get("conflicts", []),
                        "checks": f.get("verification", {}).get("checks", {}),
                    }
                ),
                result="PARTIALLY_VERIFIED" if result == "CONFLICTED" else result,
                reason=f.get("verification", {}).get("reason", ""),
                verifier_version="phase7-deterministic-v1",
            )
        )
        for ev in f.get("evidence", [])[: int(getattr(settings, "RAG_MAX_EVIDENCE_PER_EVENT", 3))]:
            db.add(
                models.ClaimEvidence(
                    claim_id=claim.id,
                    frame_id=None,
                    timestamp=ev.get("timestamp"),
                    evidence_type="forensic_evidence",
                    relevance_score=ev.get("score"),
                )
            )
        db.flush()

    for te in timeline:
        db.add(
            models.TimelineEvent(
                investigation_id=inv_id,
                timestamp=float(te.get("timestamp") or 0.0),
                description=(te.get("description") or "")[:1000],
                status=te.get("status", "UNVERIFIED"),
                # Phase 3's TimelineEventOut expects a list here; leaving it null
                # keeps that schema intact while the run's own result.timeline
                # carries the full evidence linkage.
                evidence_ids=None,
            )
        )
    db.commit()