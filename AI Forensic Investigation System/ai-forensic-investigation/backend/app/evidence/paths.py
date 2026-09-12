"""Deterministic evidence storage paths + byte-identity hashing (Phase 5).

Object locations are deterministic and collision-resistant
(``live/<camera>/<session>/<date>/<evidence-id>/original.jpg``) so the same
evidence id always maps to the same object and paths never depend on untrusted
input. A source frame's identity for dedup is its exact stored bytes (SHA-256)
scoped to the camera+session that captured it - only identical re-captures are
deduplicated, never merely similar content.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional


def evidence_object_name(
    public_id: str,
    camera_id: int | None,
    session_id: int | None,
    ext: str = ".jpg",
    date: Optional[str] = None,
) -> str:
    """Deterministic object name inside the storage bucket.

    ``date`` defaults to UTC today so capture-day partitioning is stable; callers
    may pass an explicit date string to keep tests deterministic.
    """
    day = date or datetime.utcnow().strftime("%Y-%m-%d")
    cam = int(camera_id) if camera_id is not None else 0
    ses = int(session_id) if session_id is not None else 0
    name = f"live/{cam}/{ses}/{day}/{public_id}/original{ext}"
    return name


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dedup_identity(sha256: str, camera_id: int | None, session_id: int | None) -> str:
    """Stable dedup key: exact bytes + camera + session that captured them."""
    return f"{sha256}:{camera_id or 0}:{session_id or 0}"


def sanitize_ext(value: str) -> str:
    """Normalise a MIME-ish extension to a safe lowercase alnum one."""
    cleaned = "".join(ch for ch in value.strip().lstrip(".").lower() if ch.isalnum())
    return cleaned or "jpg"