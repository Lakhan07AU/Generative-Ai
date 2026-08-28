from sqlalchemy.orm import Session

from app.database.models import AuditLog


def record_audit(
    db: Session,
    action: str,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: str | None = None,
) -> AuditLog:
    """Record an audit entry. Commits immediately so it persists independently."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def log_agent_invocation(db: Session, investigation_id: int, user_id: int | None, query: str) -> None:
    record_audit(
        db,
        "agent_invocation",
        user_id=user_id,
        entity_type="investigation",
        entity_id=investigation_id,
        details=f"investigation_id={investigation_id} query={query[:200]}",
    )


def log_tool_call(
    db: Session,
    investigation_id: int,
    user_id: int | None,
    tool_name: str,
    args_summary: str,
    status: str = "ok",
) -> None:
    """Log a single tool call with a summary of its arguments (never secrets)."""
    record_audit(
        db,
        f"tool_call:{tool_name}",
        user_id=user_id,
        entity_type="investigation",
        entity_id=investigation_id,
        details=f"investigation_id={investigation_id} tool={tool_name} status={status} args={args_summary[:500]}",
    )


def log_verification(db: Session, investigation_id: int, user_id: int | None, claim_id: int, result: str) -> None:
    record_audit(
        db,
        "evidence_verification",
        user_id=user_id,
        entity_type="claim",
        entity_id=claim_id,
        details=f"investigation_id={investigation_id} claim_id={claim_id} result={result}",
    )


def log_timeline_generation(db: Session, investigation_id: int, user_id: int | None, count: int) -> None:
    record_audit(
        db,
        "timeline_generation",
        user_id=user_id,
        entity_type="investigation",
        entity_id=investigation_id,
        details=f"investigation_id={investigation_id} events={count}",
    )
