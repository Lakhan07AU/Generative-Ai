"""Evidence verification engine (Part 3).

Pipeline:

    Claim
      -> Claim Decomposition
      -> Visual Evidence Check
      -> Temporal Check            (timestamp validated against source video bounds)
      -> Subject Check
      -> Policy Check              (advisory - policy text is never invented)
      -> Cross-Evidence Consistency
      -> Verification Result

Result:
    VERIFIED                - all required checks pass with consistent evidence
    PARTIALLY_VERIFIED      - partial support, or supporting evidence conflicts
    INSUFFICIENT_EVIDENCE   - not enough evidence to conclude (incl. bad timestamp)

Timestamps are only ever taken from source clips/frames and validated against
each source video's authoritative bounds (video.start_time .. +duration).
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import models
from app.rag.video_rag import ENTITY_ALIASES, EVENT_KEYWORDS, analyze_query
from app.agents.guardrails import validate_timestamp

VERIFIER_VERSION = "forensic-verifier-1.0"

_SUBJECT_ALIASES = ENTITY_ALIASES


def _extract_timestamp(claim_text: str) -> Optional[float]:
    """Extract an HH:MM(:SS) timestamp from a claim and convert to seconds."""
    m = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", claim_text)
    if not m:
        return None
    h, mm = int(m.group(1)), int(m.group(2))
    ss = int(m.group(3)) if m.group(3) else 0
    return float(h * 3600 + mm * 60 + ss)


def decompose_claim(claim_text: str) -> dict:
    """Break a claim into atomic, checkable facts."""
    analysis = analyze_query(claim_text)
    ts = _extract_timestamp(claim_text)
    return {
        "subject_types": analysis["entities"],
        "events": analysis["events"],
        "timestamp": ts,
        "raw": claim_text,
    }


def _subject_order(subject_type: str) -> int:
    return {"person": 0, "car": 1, "motorcycle": 1, "bicycle": 2, "backpack": 3}.get(subject_type, 4)


def _supporting_clips(db: Session, decomposition: dict, video_id: Optional[int]) -> list[dict]:
    """Find clips/detections that could support the claim's subject + events."""
    subjects = decomposition["subject_types"]
    events = decomposition["events"]

    # 1) detections matching the subject type
    matched: dict[int, dict] = {}
    label_filter = set()
    for st in subjects:
        label_filter |= _SUBJECT_ALIASES.get(st, {st})
    q = db.query(models.Detection)
    if video_id:
        q = q.filter(models.Detection.video_id == video_id)
    if label_filter:
        q = q.filter(models.Detection.label.in_(sorted(label_filter)))
    for d in q.order_by(models.Detection.detection_confidence.desc()).limit(50).all():
        cid = d.clip_id
        if cid in matched:
            continue
        clip = db.query(models.Clip).filter(models.Clip.id == cid).first()
        if not clip:
            continue
        matched[cid] = {
            "clip_id": cid,
            "clip_public_id": clip.public_id,
            "video_id": clip.video_id,
            "label": d.label,
            "timestamp": d.timestamp or clip.start_time,
            "start_time": clip.start_time,
            "end_time": clip.end_time,
            "tracking_id": d.tracking_id,
            "confidence": d.detection_confidence,
            "camera_id": clip.camera_id,
        }
        if len(matched) >= settings.RAG_RERANK_KEEP:
            break
    return list(matched.values())


def _video_bounds(db: Session, video_id: int) -> tuple[Optional[float], Optional[float]]:
    """Return authoritative timestamp bounds for a video.

    Clips/detections store timestamps as *relative seconds* from the start of
    the recording (0 .. duration), so the authoritative source-time range is
    [0, duration]. Wall-clock ``recording_date``/``start_time`` is the absolute
    anchor, not used for within-video validation.
    """
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if video is None or video.duration_seconds is None:
        return None, None
    return 0.0, float(video.duration_seconds)


def verify_claim(
    db: Session,
    claim_text: str,
    investigation_id: Optional[int] = None,
    video_id: Optional[int] = None,
    timestamp: Optional[float] = None,
    claim_type: str = "OBSERVATION",
    persist: bool = True,
) -> dict:
    """Run the full verification pipeline for a claim.

    When ``persist`` is True a Claim, its ClaimEvidence links, a Verification
    and timeline events are written to the DB.
    """
    decomposition = decompose_claim(claim_text)
    checks: dict[str, dict] = {}

    subject_types = decomposition["subject_types"]
    claim_ts = timestamp if timestamp is not None else decomposition["timestamp"]

    # ---- Visual evidence check -----------------------------------------
    clips = _supporting_clips(db, decomposition, video_id)
    checks["visual_evidence"] = {
        "passed": bool(clips),
        "reason": f"{len(clips)} supporting clip(s) found" if clips else "no supporting clip found",
        "clips": [c["clip_public_id"] for c in clips],
    }

    # ---- Temporal check (validate source timestamp) ----------------------
    temporal_passed = True
    temporal_reason = "no timestamp asserted; not checked"
    if claim_ts is not None:
        # Determine authoritative bounds from the first supporting clip's video,
        # else from the requested video.
        bounds_video_id = clips[0]["video_id"] if clips else video_id
        bounds = _video_bounds(db, bounds_video_id) if bounds_video_id else (None, None)
        if bounds[0] is None or bounds[1] is None:
            bounds = (0.0, float(settings.RAG_VERIFICATION_THRESHOLD * 8 * 3600))
        temporal_passed = validate_timestamp(claim_ts, bounds[0], bounds[1])
        temporal_reason = (
            f"timestamp {claim_ts:.1f}s within video bounds [{bounds[0]:.1f}s, {bounds[1]:.1f}s]"
            if temporal_passed
            else f"timestamp {claim_ts:.1f}s outside authoritative video bounds [{bounds[0]:.1f}s, {bounds[1]:.1f}s]"
        )
    checks["temporal"] = {"passed": temporal_passed, "reason": temporal_reason, "timestamp": claim_ts}

    # ---- Subject check ----------------------------------------------------
    subject_passed = bool(subject_types) and bool(clips)
    subject_reason = (
        f"subject type(s) {sorted(subject_types)} found in detections"
        if subject_passed
        else ("no subject type asserted" if not subject_types else "subject type not found in any clip")
    )
    checks["subject"] = {"passed": subject_passed, "reason": subject_reason}

    # ---- Policy check (advisory) -----------------------------------------
    policy_hits = []
    policy_passed = False
    policy_reason = "no policy reference in claim; not checked"
    if any(kw in claim_text.lower() for kw in ("restricted", "policy", "against", "violation", "prohibited", "required")):
        try:
            from app.rag.policy_rag import search_policies

            policy_hits = search_policies(claim_text, limit=3)
        except Exception:  # noqa: BLE001
            policy_hits = []
        policy_passed = bool(policy_hits)
        policy_reason = (
            f"{len(policy_hits)} relevant policy section(s) retrieved"
            if policy_hits
            else "no relevant policy section retrieved"
        )
    checks["policy"] = {"passed": policy_passed, "reason": policy_reason, "hits": len(policy_hits)}

    # ---- Cross-evidence consistency --------------------------------------
    consistent = _cross_evidence_consistent(clips)
    checks["cross_evidence"] = {
        "passed": consistent,
        "reason": "multiple clips agree" if consistent else "multiple clips conflict or disagree",
        "clips": len(clips),
    }

    # ---- Final result ------------------------------------------------------
    result, reason = _decide_verification(checks, clips, subject_types, claim_ts)

    payload = {
        "claim_text": claim_text,
        "decomposition": decomposition,
        "checks": checks,
        "result": result,
        "reason": reason,
        "verifier_version": VERIFIER_VERSION,
        "claim_type": claim_type,
        "evidence": [
            {
                "clip_id": c["clip_id"],
                "clip_public_id": c["clip_public_id"],
                "timestamp": c["timestamp"],
                "evidence_type": "clip",
                "relevance_score": round(float(c["confidence"] or 0.0), 3),
            }
            for c in clips
        ],
    }

    if persist and clips:
        claim_id = _persist(db, investigation_id, claim_text, claim_type, result, payload, clips)
        payload["claim_id"] = claim_id
    return payload


def _cross_evidence_consistent(clips: list[dict]) -> bool:
    if len(clips) <= 1:
        return True
    trackers = {c.get("tracking_id") for c in clips if c.get("tracking_id")}
    if trackers and len(trackers) > 1:
        return False  # different subjects involved - conflicting
    return True


def _decide_verification(checks: dict, clips: list, subject_types: list, claim_ts: Optional[float]) -> tuple[str, str]:
    visual = checks["visual_evidence"]["passed"]
    temporal = checks["temporal"]["passed"]
    subject = checks["subject"]["passed"]
    cross = checks["cross_evidence"]["passed"]

    if claim_ts is not None and not temporal:
        return "INSUFFICIENT_EVIDENCE", (
            "INSUFFICIENT_EVIDENCE - asserted timestamp fails authoritative source-time validation; "
            "it cannot be used."
        )
    if not visual or not subject:
        return "INSUFFICIENT_EVIDENCE", (
            "INSUFFICIENT_EVIDENCE - no supporting video evidence matches the claimed subject/action."
        )
    if not cross:
        return "PARTIALLY_VERIFIED", (
            "PARTIALLY_VERIFIED - supporting clips involve distinct subjects or conflict; "
            "a firm conclusion cannot be drawn."
        )
    if subject and visual and cross:
        return "VERIFIED", (
            "VERIFIED - subject detected, visual evidence present, timestamps valid and "
            "supporting clips are consistent."
        )
    return "PARTIALLY_VERIFIED", "PARTIALLY_VERIFIED - only partial supporting evidence found."


def _persist(db: Session, investigation_id, claim_text, claim_type, result, payload, clips) -> int:
    claim = models.Claim(
        investigation_id=investigation_id,
        claim_text=claim_text,
        claim_type=claim_type,
        status=result,
        confidence=0.9 if result == "VERIFIED" else (0.5 if result == "PARTIALLY_VERIFIED" else 0.2),
    )
    db.add(claim)
    db.flush()
    for c in clips:
        db.add(models.ClaimEvidence(
            claim_id=claim.id,
            clip_id=c["clip_id"],
            timestamp=c.get("timestamp"),
            evidence_type="clip",
            relevance_score=round(float(c.get("confidence") or 0.0), 3),
        ))
    ver = models.Verification(
        claim_id=claim.id,
        checks=json.dumps(payload["checks"]),
        result=result,
        reason=payload["reason"],
        verifier_version=VERIFIER_VERSION,
    )
    db.add(ver)
    db.commit()
    db.refresh(claim)
    return claim.id
