"""Security Policy API (Part 2).

Routes:
  POST /policies/upload         - upload + index a security policy document (ADMIN)
  GET  /policies                - list policies
  GET  /policies/{policy_id}    - policy + its sections
  GET  /policies/{policy_id}/sections - view policy sections
  POST /policies/search         - semantic search across policies
"""

import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database import models
from app.schemas.rag import PolicyOut, PolicyChunkOut, PolicySearchHit
from app.auth.deps import get_current_user, require_roles
from app.rag.policy_rag import ingest_policy, search_policies, ALLOWED_EXTENSIONS
from app.storage.service import storage

router = APIRouter(prefix="/policies", tags=["policies"])


def _to_policy_out(policy: models.PolicyDocument) -> dict:
    return {
        "policy_id": policy.policy_id,
        "document_name": policy.document_name,
        "filename": policy.filename,
        "source_format": policy.source_format,
        "status": policy.status,
        "created_at": policy.created_at,
        "chunk_count": len(policy.chunks),
    }


@router.post("/upload", response_model=PolicyOut, status_code=status.HTTP_201_CREATED)
def upload_policy(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("ADMIN")),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {sorted(ALLOWED_EXTENSIONS)}")

    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Store original in MinIO for record
    storage_path = None
    try:
        storage.ensure_buckets()
        storage_path = storage.put_file(
            "policies",
            _bytes_to_file(data, ext),
            storage.unique_name("policy", ext),
            content_type=_content_type(ext),
        )
    except Exception:  # noqa: BLE001
        storage_path = None

    try:
        result = ingest_policy(file.filename or "policy", data, user_id=current_user.id, storage_path=storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    policy = db.query(models.PolicyDocument).filter(models.PolicyDocument.policy_id == result["policy_id"]).first()
    return _to_policy_out(policy)


@router.get("", response_model=list[PolicyOut])
def list_policies(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    policies = db.query(models.PolicyDocument).order_by(models.PolicyDocument.id.desc()).all()
    return [_to_policy_out(p) for p in policies]


@router.get("/{policy_id}", response_model=dict)
def get_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    policy = db.query(models.PolicyDocument).filter(models.PolicyDocument.policy_id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return {
        **_to_policy_out(policy),
        "chunks": [
            {
                "id": c.id,
                "section": c.section,
                "page": c.page,
                "chunk_index": c.chunk_index,
                "text": c.text,
            }
            for c in policy.chunks
        ],
    }


@router.get("/{policy_id}/sections", response_model=list[PolicyChunkOut])
def get_policy_sections(
    policy_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    policy = db.query(models.PolicyDocument).filter(models.PolicyDocument.policy_id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return sorted(policy.chunks, key=lambda c: (c.chunk_index or 0))


@router.post("/search", response_model=list[PolicySearchHit])
def policy_search(
    payload: dict,
    current_user: models.User = Depends(get_current_user),
):
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    return search_policies(query, limit=10)


def _bytes_to_file(data: bytes, ext: str) -> str:
    import tempfile

    fd, path = tempfile.mkstemp(suffix=ext)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def _content_type(ext: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
    }.get(ext, "application/octet-stream")
