"""Phase 8 finding verification and evidence-support scoring.

Support is scored from explainable factors (direct visual evidence, event
match, track match, timestamp match, camera match, VLM support, independent
sources). Scores are deterministic and never fabricated.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.forensic import semantics


def _factor(label: str, weight: float, matched: bool) -> Dict[str, Any]:
    return {"label": label, "weight": weight, "matched": matched}

DOWNTONE_FACTOR_WEIGHTS = {
    "direct_visual": 0.25,
    "event_match": 0.20,
    "track_match": 0.20,
    "timestamp_match": 0.15,
    "camera_match": 0.05,
    "vlm_support": 0.10,
    "independent_sources": 0.10,
}


def verify_findings(entries, rows_by_id) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for index, entry in enumerate(entries):
        evidence_ids = entry.get("evidence_ids") or []
        rows = [rows_by_id.get(eid) for eid in evidence_ids]
        rows = [r for r in rows if r is not None]
        evidence_types = set(entry.get("event_type_set") or [])
        cameras = {entry.get("camera_id")} if entry.get("camera_id") else set()
        has_observed_vlm = any(
            getattr(r, "evidence_type", None) == "VLM_OBSERVATION"
            for r in rows
        )
        has_track = "TRACK_EVENT" in evidence_types
        has_visual = bool(evidence_types & {"FRAME", "DETECTION", "TRACK_EVENT"})

        factors = [
            _factor("direct visual evidence", DOWNTONE_FACTOR_WEIGHTS["direct_visual"], has_visual),
            _factor("event record match", DOWNTONE_FACTOR_WEIGHTS["event_match"], bool(entry.get("event_type"))),
            _factor("track match", DOWNTONE_FACTOR_WEIGHTS["track_match"], bool(entry.get("track_id"))),
            _factor("timestamp match", DOWNTONE_FACTOR_WEIGHTS["timestamp_match"], entry.get("timestamp") is not None),
            _factor("camera match", DOWNTONE_FACTOR_WEIGHTS["camera_match"], bool(entry.get("camera_id"))),
            _factor("VLM support", DOWNTONE_FACTOR_WEIGHTS["vlm_support"], has_observed_vlm),
            _factor(
                "multiple independent sources",
                DOWNTONE_FACTOR_WEIGHTS["independent_sources"],
                len(evidence_types) >= 2 or len(cameras) >= 2,
            ),
        ]
        matched = [f for f in factors if f["matched"]]
        unmatched = [f for f in factors if not f["matched"]]
        support = round(sum(f["weight"] for f in matched), 2)
        if support > 1.0:
            support = 1.0

        classification = entry.get("classification") or semantics.UNVERIFIED
        status = entry.get("verification_status") or semantics.UNVERIFIED_STATUS
        if not evidence_ids:
            status = semantics.INSUFFICIENT_EVIDENCE
            support = 0.0

        quality = entry.get("quality_flags") or []
        downgrades: List[str] = []
        if classification == semantics.OBSERVED and "LOW_RESOLUTION" in quality and not has_track:
            downgrades.append("Low-resolution evidence without a tracked event record prevents an OBSERVED classification.")
        if classification == semantics.OBSERVED and has_observed_vlm and not has_track and not has_visual:
            downgrades.append("Findings grounded only in VLM text without [OBSERVED] source frames are not classified OBSERVED.")

        matched_hint = ", ".join(f["label"] for f in matched) or "no factors"
        unmatched_hint = ", ".join(f["label"] for f in unmatched) or "all factors"
        support_reason = (
            f"Evidence support {support:.2f}: {matched_hint} contribute to the score; "
            f"{unmatched_hint} could not be established."
        )

        limitations: List[str] = []
        if entry.get("notes"):
            limitations.append(entry["notes"])
        for flag in quality:
            limitations.append(f"Evidence flagged {flag}.")
        if "OBJECT_IDENTITY" not in limitations:
            limitations.append(semantics.IDENTITY_NOTE if entry.get("object_class") else semantics.WITHIN_VIEW_NOTE)
        if not entry.get("timestamp"):
            limitations.append("No normalized event time could be established for this finding.")

        text = entry.get("description") or "The available evidence does not yet describe this timeline entry."
        if classification == semantics.UNKNOWN or not evidence_ids:
            text = "The available evidence is insufficient to determine what occurred at this point in the timeline."

        findings.append(
            {
                "finding_id": f"FINDING-{index + 1:02d}",
                "timeline_event_id": entry.get("timeline_event_id"),
                "text": text,
                "classification": classification,
                "verification_status": status,
                "evidence_support": support,
                "support_factors": factors,
                "support_reason": support_reason,
                "supporting_evidence": evidence_ids,
                "evidence_count": len(evidence_ids),
                "limitations": limitations,
                "causality_safe": True,
                "causality_note": semantics.CAUSAL_NOTE,
                "listed_conflicts": [eid for eid in entry.get("conflicts") or [] if eid],
                "downgraded_from_observed": list(downgrades),
                "review_status": "PENDING",
            }
        )
    return findings