"""Phase 7 - inspectable plan generator.

Produces a list of tool steps the bounded graph will attempt during a run. Each
step names the tool to call, its arguments, and the investigative purpose it
serves. The plan is persisted with the run so a human can review the agent's
intent before execution, and step history is stored after execution for audit.

Plans are category-driven: the classification node selects a template; the
planner fills in query-specific parameters (track id, camera hint, evidence ids).
Each plan is bounded by the same graph caps that guard execution.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.investigator.query import CAT_CAMERA, CAT_COMBINED, CAT_EVIDENCE, CAT_EVENT, CAT_OBJECT, CAT_TEMPORAL, CAT_TRACK, CAT_UNANSWERABLE, CAT_VLM, CAT_OTHER


def generate_plan(classification: Dict[str, Any], top_k: int = 8) -> List[Dict[str, Any]]:
    """Return an ordered list of bounded tool steps for the investigation."""
    cat = classification.get("category", CAT_OTHER)
    track_id = classification.get("tracking_id")
    camera_hint = classification.get("camera_hint")
    evidence_ids = classification.get("evidence_ids") or []
    raw_query = classification.get("raw", "")

    if cat == CAT_UNANSWERABLE:
        return _unanswerable_plan(classification)

    if cat == CAT_TRACK:
        return _track_plan(classification, track_id, top_k)

    if cat == CAT_CAMERA:
        return _camera_plan(classification, camera_hint, top_k)

    if cat == CAT_EVIDENCE:
        return _evidence_plan(classification, evidence_ids, raw_query, top_k)

    if cat == CAT_VLM:
        return _vlm_plan(classification, top_k)

    if cat == CAT_COMBINED:
        return _combined_plan(classification, top_k)

    if cat in (CAT_EVENT, CAT_OBJECT):
        return _event_or_object_plan(classification, cat, top_k)

    if cat == CAT_TEMPORAL:
        return _temporal_plan(classification, top_k)

    # OTHER / fallback
    return _other_plan(classification, top_k)


# ---------------------------------------------------------------------------
# Plan templates
# ---------------------------------------------------------------------------


def _unanswerable_plan(classification: Dict[str, Any]) -> List[Dict[str, Any]]:
    reason = classification.get("category_reason", "unanswerable question")
    return [
        {
            "step": 1,
            "node": "classify",
            "tool": "policy",
            "args": {},
            "purpose": "Query cannot be answered from footage: " + reason,
        },
    ]


def _track_plan(classification: Dict[str, Any], track_id: str, top_k: int) -> List[Dict[str, Any]]:
    return [
        {
            "step": 1,
            "node": "retrieve",
            "tool": "get_track",
            "args": {"tracking_id": track_id, "top_k": top_k},
            "purpose": f"Collect all evidence for track {track_id}",
        },
        {
            "step": 2,
            "node": "verify",
            "tool": "conflict_check",
            "args": {},
            "purpose": "Detect any contradictory events within the track",
        },
    ]


def _camera_plan(classification: Dict[str, Any], camera_hint: str, top_k: int) -> List[Dict[str, Any]]:
    return [
        {
            "step": 1,
            "node": "retrieve",
            "tool": "camera_evidence",
            "args": {"camera_name": camera_hint, "limit": top_k},
            "purpose": f"Retrieve all evidence on camera '{camera_hint}'",
        },
    ]


def _evidence_plan(classification: Dict[str, Any], evidence_ids: List[str], raw: str, top_k: int) -> List[Dict[str, Any]]:
    steps = []
    if evidence_ids:
        for eid in evidence_ids[:3]:
            steps.append(
                {
                    "step": len(steps) + 1,
                    "node": "retrieve",
                    "tool": "evidence_detail",
                    "args": {"evidence_id": eid},
                    "purpose": f"Fetch detail for {eid}",
                }
            )
    else:
        steps.append(
            {
                "step": 1,
                "node": "retrieve",
                "tool": "search_evidence",
                "args": {"query": raw, "top_k": top_k},
                "purpose": "Broad evidence search for evidence inquiry",
            }
        )
    steps.append(
        {
            "step": len(steps) + 1,
            "node": "verify",
            "tool": "conflict_check",
            "args": {},
            "purpose": "Validate supporting evidence for conflicts",
        }
    )
    return steps


def _vlm_plan(classification: Dict[str, Any], top_k: int) -> List[Dict[str, Any]]:
    return [
        {
            "step": 1,
            "node": "retrieve",
            "tool": "list_observations",
            "args": {"limit": top_k},
            "purpose": "Collect VLM observations for visual context",
        },
    ]


def _event_or_object_plan(classification: Dict[str, Any], cat: str, top_k: int) -> List[Dict[str, Any]]:
    return [
        {
            "step": 1,
            "node": "retrieve",
            "tool": "search_evidence",
            "args": {"query": classification.get("raw", ""), "top_k": top_k},
            "purpose": f"Retrieve candidate evidence for {cat.lower()} query",
        },
    ]


def _temporal_plan(classification: Dict[str, Any], top_k: int) -> List[Dict[str, Any]]:
    return [
        {
            "step": 1,
            "node": "retrieve",
            "tool": "search_evidence",
            "args": {"query": classification.get("raw", ""), "top_k": top_k},
            "purpose": "Retrieve evidence within the temporal window",
        },
    ]


def _combined_plan(classification: Dict[str, Any], top_k: int) -> List[Dict[str, Any]]:
    steps = [
        {
            "step": 1,
            "node": "retrieve",
            "tool": "search_evidence",
            "args": {"query": classification.get("raw", ""), "top_k": top_k},
            "purpose": "Broad evidence retrieval combining all detected signals",
        },
    ]
    if classification.get("tracking_id"):
        steps.append(
            {
                "step": 2,
                "node": "retrieve",
                "tool": "get_track",
                "args": {"tracking_id": classification["tracking_id"], "top_k": top_k},
                "purpose": f"Focused track retrieval for {classification['tracking_id']}",
            }
        )
    if classification.get("camera_hint"):
        steps.append(
            {
                "step": len(steps) + 1,
                "node": "retrieve",
                "tool": "camera_evidence",
                "args": {"camera_name": classification["camera_hint"], "limit": top_k},
                "purpose": f"Camera-scope retrieval for '{classification['camera_hint']}'",
            }
        )
    steps.append(
        {
            "step": len(steps) + 1,
            "node": "verify",
            "tool": "conflict_check",
            "args": {},
            "purpose": "Detect conflicting signals across retrieval sources",
        }
    )
    return steps


def _other_plan(classification: Dict[str, Any], top_k: int) -> List[Dict[str, Any]]:
    return [
        {
            "step": 1,
            "node": "retrieve",
            "tool": "search_evidence",
            "args": {"query": classification.get("raw", ""), "top_k": top_k},
            "purpose": "General evidence retrieval for unclassified query",
        },
    ]