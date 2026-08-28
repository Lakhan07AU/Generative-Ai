"""Query understanding -> tool-selection planner (Part 3).

In simulation mode this is the deterministic "Tool Selection" stage: it turns a
natural-language query into an ordered plan of tool invocations for the
bounded investigation agent, derived from observable keyword/entity analysis
(never from fabricated intent).

When a live LLM provider is configured the plan may be refined via
provider.generate_text, but the default path is deterministic for testing.
"""

from __future__ import annotations

import re
from typing import Optional

from app.core.config import settings
from app.rag.video_rag import ENTITY_ALIASES, analyze_query
from app.ai import provider

# YOLO-style object labels we can search for by exact detections.
OBJECT_LABELS = {
    "person": "person", "car": "car", "truck": "truck", "van": "car",
    "bus": "bus", "motorcycle": "motorcycle", "motorbike": "motorcycle",
    "bicycle": "bicycle", "bike": "bicycle", "backpack": "backpack", "bag": "backpack",
}

EVENT_QUERY_TOOL = ["entered", "leaving", "crossed", "approached", "running", "walking", "carrying", "stopped", "alarm"]


def _detect_object_token(query: str) -> Optional[str]:
    q = query.lower()
    for token, label in OBJECT_LABELS.items():
        if re.search(rf"\b{re.escape(token)}\b", q):
            return label
    return None


def _detect_person(query: str) -> bool:
    q = query.lower()
    return any(a in q for a in ENTITY_ALIASES.get("person", set()))


def _detect_policy_intent(query: str) -> bool:
    q = query.lower()
    return any(k in q for k in ("restricted", "policy", "against", "violation", "prohibited", "required", "allowed", "permitted"))


def _detect_event(query: str) -> Optional[str]:
    q = query.lower()
    for ev in EVENT_QUERY_TOOL:
        if ev in q:
            return ev
    return None


def build_plan(db, query: str, video_id: Optional[int] = None) -> list[dict]:
    """Return an ordered list of tool-invocation dicts: {tool, arguments}.

    Honors the maximum-tool-calls budget by capping the plan length.
    """
    analysis = analyze_query(query)
    plan: list[dict] = []

    plan.append({"tool": "search_video", "arguments": {"query": query, "video_id": video_id}})

    if _detect_person(query):
        plan.append({"tool": "search_person", "arguments": {"limit": 5, "video_id": video_id}})

    obj = _detect_object_token(query)
    if obj:
        plan.append({"tool": "search_object", "arguments": {"label": obj, "limit": 5, "video_id": video_id}})

    ev = _detect_event(query)
    if ev:
        plan.append({"tool": "search_event", "arguments": {"event_type": ev, "video_id": video_id, "limit": 20}})

    if _detect_policy_intent(query):
        plan.append({"tool": "search_policy", "arguments": {"query": query, "limit": 4}})

    plan.append({"tool": "build_timeline", "arguments": {"video_id": video_id}})

    # Cap the static plan to leave room for get_clip/verify refinement.
    budget_floor = max(1, settings.AGENT_MAX_TOOL_CALLS - 4)
    plan = plan[:budget_floor]
    return plan


def refine_with_llm(query: str, plan: list[dict]) -> list[dict]:
    """Optionally let a configured LLM refine the tool plan. Falls back to plan."""
    if not provider.available():
        return plan
    try:
        names = ", ".join(p["tool"] for p in plan)
        text = provider.generate_text(
            f"Given the investigation query '{query}', refine this tool plan: [{names}]. "
            "Return only a comma-separated list of tool names from this exact set. "
            "Do not add tools outside: search_video, search_person, search_object, search_event, "
            "get_clip, get_frame, search_policy, build_timeline, verify_evidence."
        )
        ordered = [t.strip() for t in re.split(r"[,;]", text) if t.strip()]
        plan_by_name = {p["tool"]: p for p in plan}
        refined = [plan_by_name[t] for t in ordered if t in plan_by_name]
        return refined or plan
    except Exception:  # noqa: BLE001
        return plan
