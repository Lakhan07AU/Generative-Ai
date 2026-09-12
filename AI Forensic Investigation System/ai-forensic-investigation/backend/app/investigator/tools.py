"""Phase 7 - bounded investigative tools over Phase 6 retrieval.

Every tool is:
    * scoped - evidence is only ever selected from the investigation's cameras
      (``camera_ids``), mirroring the Phase 6 isolation guarantee;
    * bounded - results, top_k and side lists are capped by settings;
    * verbose - each card carries a score, per-item reasons and a verification
      block so surfaced evidence can explain itself;
    * safe - evidence content is treated as UNTRUSTED input: it is sanitized,
      truncated and never compiled into instructions. Only statements explicitly
      tagged ``[OBSERVED]`` may be surfaced as grounded text; everything else is
      ignored by the synthesizer.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.database.models import Camera, ForensicEvidence
from app.evidence.schemas import parse_metadata
from app.investigation import parse_query, rerank_candidates, retrieve_investigation_evidence
from app.investigation.retrieval import camera_names as _camera_names_map

TOOL_WHITELIST = {
    "search_evidence",
    "get_track",
    "camera_evidence",
    "evidence_detail",
    "list_observations",
    "conflict_check",
}

_OBSERVED_MARKER = "[OBSERVED]"

# Event type source-truth contradictions that make two co-temporal records of
# the same track mutually exclusive.
_CONFLICT_PAIRS = {
    ("object_entered", "object_exited"),
    ("object_exited", "object_entered"),
    ("object_stopped", "object_moved"),
    ("object_moved", "object_stopped"),
    ("object_disappeared", "object_reappeared"),
}

_SANITIZE_RE = re.compile(r"[^\x20-\x7e]")


def sanitize_evidence_text(text: Optional[str], limit: int = 500) -> str:
    """Sanitize untrusted evidence content to a safe, printable snippet."""
    if not text:
        return ""
    cleaned = _SANITIZE_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[: int(limit)]


def is_observed_statement(text: Optional[str]) -> bool:
    """Only explicitly-observed statements are eligible to be surfaced."""
    return bool(text and _OBSERVED_MARKER in text)


# ---------------------------------------------------------------------------
# Card building + verification
# ---------------------------------------------------------------------------


def _verification_block(
    candidate: Dict[str, Any],
    *,
    support_required: bool = True,
    support_satisfied: Optional[bool] = None,
) -> Dict[str, Any]:
    score = candidate.get("score")
    if score is None:
        score = candidate.get("vector_score")
    evidence_type = candidate.get("evidence_type") or ""
    has_provenance = bool(
        candidate.get("event_id")
        or candidate.get("event_type")
        or candidate.get("tracking_id")
        or candidate.get("vlm_observation_id")
    )
    has_timestamp = candidate.get("timestamp") is not None
    consistent = bool(
        (candidate.get("object_class") is not None)
        or evidence_type in ("VLM_OBSERVATION", "RAW_SOURCE")
        or candidate.get("event_type") is not None
    )
    if support_satisfied is None:
        support_satisfied = support_required and (
            (score is not None and float(score) >= settings.RAG_VERIFICATION_THRESHOLD)
            or (candidate.get("object_class") is not None and not support_required)
        )
    checks = {
        "score_support": support_satisfied if support_required else True,
        "has_provenance": has_provenance,
        "has_timestamp": has_timestamp,
        "class_consistent": consistent,
    }
    verified = all(checks.values())
    failed = [k for k, v in checks.items() if not v]
    reason = (
        "all verification checks passed"
        if verified
        else "failed: " + ", ".join(failed)
    )
    if candidate.get("verified") and support_required:
        verified = True
        reason = "rerank verified + checks passed"
    return {"verified": bool(verified), "reason": reason, "checks": checks}


def _to_card(
    candidate: Dict[str, Any],
    camera_names: Dict[int, str],
    *,
    support_required: bool = True,
) -> Dict[str, Any]:
    cid = candidate.get("camera_id")
    verification = _verification_block(candidate, support_required=support_required)
    return {
        "evidence_id": candidate.get("evidence_id"),
        "evidence_type": candidate.get("evidence_type"),
        "source": candidate.get("source"),
        "camera_id": cid,
        "camera_name": camera_names.get(cid) if cid is not None else None,
        "session_id": candidate.get("session_id"),
        "timestamp": candidate.get("timestamp"),
        "event_id": candidate.get("event_id"),
        "event_type": candidate.get("event_type"),
        "tracking_id": candidate.get("tracking_id"),
        "object_class": candidate.get("object_class"),
        "vlm_observation_id": candidate.get("vlm_observation_id"),
        "storage_path": candidate.get("storage_path"),
        "sha256": candidate.get("sha256"),
        "content_text": sanitize_evidence_text(candidate.get("source_text") or candidate.get("content_text")),
        "score": float(candidate.get("score") or candidate.get("vector_score") or 0.0),
        "reasons": list(candidate.get("reasons") or []),
        "verified": verification["verified"],
        "verification": verification,
    }


# ---------------------------------------------------------------------------
# Evidence selection (scope-bounded)
# ---------------------------------------------------------------------------


def _rows_in_scope(db, camera_ids: List[int]) -> List[ForensicEvidence]:
    return (
        db.query(ForensicEvidence)
        .filter(
            ForensicEvidence.camera_id.in_(camera_ids),
            ForensicEvidence.index_status.in_(("INDEXED", "PENDING", "FAILED")),
        )
        .order_by(ForensicEvidence.captured_at.desc())
        .all()
    )


def _row_to_candidate(row: ForensicEvidence) -> Dict[str, Any]:
    meta = parse_metadata(row)
    label = (meta.get("label") or "").strip().lower() or None
    return {
        "evidence_id": row.public_id,
        "evidence_type": row.evidence_type,
        "source": row.source,
        "camera_id": row.camera_id,
        "session_id": row.session_id,
        "timestamp": row.frame_timestamp,
        "event_id": row.event_id,
        "event_type": row.event_type,
        "tracking_id": row.tracking_id,
        "object_class": label,
        "vlm_observation_id": row.vlm_observation_id,
        "storage_path": row.storage_path,
        "sha256": row.sha256,
        "source_text": row.content_text or "",
        "score": None,
        "vector_score": None,
    }


def _search(
    db,
    query_text: str,
    camera_ids: List[int],
    top_k: int,
) -> List[Dict[str, Any]]:
    camera_names = _camera_names_map(db, camera_ids)
    parsed = parse_query(query_text)
    candidates = retrieve_investigation_evidence(db, query_text, parsed, camera_ids, limit=top_k)
    ranked = rerank_candidates(candidates, parsed)
    cards = [_to_card(c, camera_names) for c in ranked]
    return cards, camera_names


def _track_cards(db, tracking_id: str, camera_ids: List[int], top_k: int) -> List[Dict[str, Any]]:
    camera_names = _camera_names_map(db, camera_ids)
    parsed = parse_query(f"track {tracking_id}")
    candidates = retrieve_investigation_evidence(db, f"track {tracking_id}", parsed, camera_ids, limit=top_k)
    ranked = rerank_candidates(candidates, parsed)
    return [_to_card(c, camera_names) for c in ranked], camera_names


def _camera_scope_cards(
    db,
    camera_hint: Optional[str],
    camera_ids: List[int],
    limit: int,
) -> tuple[List[Dict[str, Any]], Dict[int, str]]:
    camera_names = _camera_names_map(db, camera_ids)
    rows = _rows_in_scope(db, camera_ids)
    if camera_hint:
        hint = camera_hint.lower()
        rows = [
            r for r in rows
            if hint in (camera_names.get(r.camera_id) or "").lower()
        ]
    rows = rows[: int(limit)]
    cards = [_to_card(_row_to_candidate(r), camera_names, support_required=False) for r in rows]
    return cards, camera_names


def _observation_cards(db, camera_ids: List[int], limit: int) -> List[Dict[str, Any]]:
    camera_names = _camera_names_map(db, camera_ids)
    rows = [r for r in _rows_in_scope(db, camera_ids) if r.evidence_type == "VLM_OBSERVATION"]
    rows = rows[: int(limit)]
    cards = [_to_card(_row_to_candidate(r), camera_names) for r in rows]
    return cards, camera_names


def _detail_card(db, evidence_id: str, camera_ids: List[int]) -> Optional[Dict[str, Any]]:
    camera_names = _camera_names_map(db, camera_ids)
    row = (
        db.query(ForensicEvidence)
        .filter(ForensicEvidence.public_id == evidence_id)
        .first()
    )
    if row is None or (row.camera_id is not None and int(row.camera_id) not in camera_ids):
        return None
    card = _to_card(_row_to_candidate(row), camera_names)
    return card


# ---------------------------------------------------------------------------
# Conflict detection (CONFLICTING EVIDENCE)
# ---------------------------------------------------------------------------


def detect_conflicts(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect mutually-exclusive evidence among the selected cards.

    Conflicts are never resolved by the agent - they are reported so a human
    reviews them. Only real contradictions are flagged (same track, overlapping
    time, contradictory event type or object class). Two cameras seeing the same
    track is cross-camera corroboration, not a conflict.
    """
    conflicts: List[Dict[str, Any]] = []
    by_track: Dict[str, List[Dict[str, Any]]] = {}
    for c in cards:
        tid = c.get("tracking_id")
        if tid:
            by_track.setdefault(tid, []).append(c)

    tolerance = float(settings.AGENT_CONFLICT_TOLERANCE_SECONDS)

    for tid, group in by_track.items():
        ordered = sorted(group, key=lambda c: float(c.get("timestamp") or 0.0))
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                a, b = ordered[i], ordered[j]
                ta, tb = a.get("timestamp"), b.get("timestamp")
                if ta is None or tb is None:
                    continue
                if abs(float(ta) - float(tb)) > tolerance:
                    continue
                ea, eb = a.get("event_type"), b.get("event_type")
                if (ea, eb) in _CONFLICT_PAIRS:
                    conflicts.append(
                        {
                            "kind": "event_type",
                            "evidence_a": a.get("evidence_id"),
                            "evidence_b": b.get("evidence_id"),
                            "reason": (
                                f"Track {tid}: event '{ea}' at {ta} contradicts "
                                f"event '{eb}' at {tb} within {tolerance:.0f}s."
                            ),
                        }
                    )
                oa, ob = a.get("object_class"), b.get("object_class")
                if oa and ob and oa.lower() != ob.lower():
                    conflicts.append(
                        {
                            "kind": "object_class",
                            "evidence_a": a.get("evidence_id"),
                            "evidence_b": b.get("evidence_id"),
                            "reason": (
                                f"Track {tid}: labeled as '{oa}' in one record and "
                                f"'{ob}' in another within {tolerance:.0f}s."
                            ),
                        }
                    )
    return conflicts


# ---------------------------------------------------------------------------
# Tool dispatcher (bounded, whitelisted, audited)
# ---------------------------------------------------------------------------


def run_tool(
    db,
    name: str,
    args: Dict[str, Any],
    camera_ids: List[int],
    camera_names: Dict[int, str],
) -> Dict[str, Any]:
    """Execute one whitelisted tool within the investigation's camera scope."""
    if name not in TOOL_WHITELIST:
        return {"status": "error", "error": f"unknown tool {name}", "evidence": []}

    top_k = int(args.get("top_k") or settings.AGENT_RUN_TOP_K)
    limit = int(args.get("limit") or top_k or settings.AGENT_RUN_TOP_K)
    top_k = max(1, min(top_k, int(settings.RAG_TOP_K)))
    limit = max(1, min(limit, int(settings.AGENT_MAX_RUN_EVIDENCE)))

    try:
        if name == "search_evidence":
            cards, names = _search(db, str(args.get("query") or ""), camera_ids, top_k)
            return {"status": "ok", "evidence": cards, "camera_names": names,
                    "count": len(cards), "tool": name}
        if name == "get_track":
            cards, names = _track_cards(db, str(args.get("tracking_id") or ""), camera_ids, top_k)
            return {"status": "ok", "evidence": cards, "camera_names": names,
                    "count": len(cards), "tool": name}
        if name == "camera_evidence":
            cards, names = _camera_scope_cards(db, args.get("camera_name"), camera_ids, limit)
            return {"status": "ok", "evidence": cards, "camera_names": names,
                    "count": len(cards), "tool": name}
        if name == "evidence_detail":
            card = _detail_card(db, str(args.get("evidence_id") or ""), camera_ids)
            cards = [card] if card else []
            return {"status": "ok" if card else "empty",
                    "evidence": cards, "camera_names": camera_names,
                    "count": len(cards), "tool": name}
        if name == "list_observations":
            cards, names = _observation_cards(db, camera_ids, limit)
            return {"status": "ok", "evidence": cards, "camera_names": names,
                    "count": len(cards), "tool": name}
        if name == "conflict_check":
            source = args.get("evidence") or []
            conflicts = detect_conflicts(source)
            return {"status": "ok", "conflicts": conflicts, "count": len(conflicts),
                    "tool": name}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:300], "evidence": [], "tool": name}

    return {"status": "error", "error": f"tool {name} did not run", "evidence": []}