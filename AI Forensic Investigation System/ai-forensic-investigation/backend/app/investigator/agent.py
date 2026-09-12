"""Phase 7 - bounded LangGraph investigation agent.

Graph (all nodes are deterministic; no free-form LLM in the loop):

    START -> classify -> plan -> [route]
        unanswerable -> synthesize -> END
        otherwise    -> retrieve -> analyze -> verify -> [route_after_verify]
            budget exceeded -> fail -> END
            expansion wanted -> expand -> analyze
            else            -> timeline -> synthesize -> END

Hard bounds, enforced at every node boundary:
    * ``AGENT_MAX_RUN_STEPS``        - node steps executed
    * ``AGENT_MAX_RUN_TOOL_CALLS``   - tool invocations
    * ``AGENT_MAX_RUN_EVIDENCE``     - evidence records merged into context
    * ``AGENT_MAX_RUN_SECONDS``      - wall-clock budget

Status machine is advanced by ``store.set_status`` which rejects illegal
transitions, so a misbehaving node cannot skip or corrupt the lifecycle. The
graph ends at READY_FOR_REVIEW (reviewable findings) or COMPLETED (nothing
reviewable); a human then approves -> COMPLETED or rejects/cancels -> CANCELLED.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.investigator.query import CAT_UNANSWERABLE, classify_query
from app.investigator.planner import generate_plan
from app.investigator import store
from app.investigator.tools import (
    detect_conflicts,
    is_observed_statement,
    run_tool,
    sanitize_evidence_text,
)

TOP_FINDING_OBSERVED = "OBSERVED"
TOP_FINDING_INFERRED = "INFERRED"
TOP_FINDING_UNKNOWN = "UNKNOWN"


class InvestState(TypedDict, total=False):
    run_id: int
    investigation_id: int
    query: str
    user_id: Optional[int]

    camera_ids: List[int]
    camera_names: Dict[int, str]

    classification: Dict[str, Any]
    plan: List[Dict[str, Any]]

    evidence_cards: List[Dict[str, Any]]
    used_evidence_ids: List[str]
    claims_internal: List[Dict[str, Any]]
    timeline: List[Dict[str, Any]]
    conflicts: List[Dict[str, Any]]

    result: Dict[str, Any]
    metrics: Dict[str, Any]

    reviewable: bool
    require_review: bool

    step_count: int
    tool_calls: int
    started_at: float
    expanded: bool
    timed_out: bool
    error: Optional[str]
    steps: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Budget helpers
# ---------------------------------------------------------------------------


def _record_node(state: InvestState, node: str, note: str = "") -> None:
    steps = state.setdefault("steps", [])
    if len(steps) < int(settings.AGENT_MAX_RUN_STEPS) * 2:
        steps.append(
            {
                "node": node,
                "note": note,
                "tool_calls": state.get("tool_calls", 0),
                "evidence": len(state.get("evidence_cards", [])),
                "ts": round(time.monotonic() - state.get("started_at", time.monotonic()), 3),
            }
        )


def _elapsed(state: InvestState) -> float:
    return time.monotonic() - state.get("started_at", time.monotonic())


def _within_steps(state: InvestState) -> bool:
    return state.get("step_count", 0) < int(settings.AGENT_MAX_RUN_STEPS)


def _within_tools(state: InvestState) -> bool:
    return state.get("tool_calls", 0) < int(settings.AGENT_MAX_RUN_TOOL_CALLS)


def _within_time(state: InvestState) -> bool:
    return _elapsed(state) < float(settings.AGENT_MAX_RUN_SECONDS)


def _within_budget(state: InvestState) -> bool:
    return _within_steps(state) and _within_tools(state) and _within_time(state)


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def _classify(db, state: InvestState) -> InvestState:
    state["classification"] = classify_query(state["query"])
    _record_node(state, "classify", state["classification"].get("category", ""))
    store.set_status(db, state["run_id"], store.PLANNING)
    store.checkpoint(db, state["run_id"], classification=state["classification"], steps=state.get("steps"))
    return state


def _plan(db, state: InvestState) -> InvestState:
    state["plan"] = generate_plan(state["classification"])
    _record_node(state, "plan", f"{len(state['plan'])} step(s)")
    store.checkpoint(db, state["run_id"], plan=state["plan"], steps=state.get("steps"))
    return state


def _retrieve(db, state: InvestState) -> InvestState:
    state["step_count"] = state.get("step_count", 0) + 1
    store.set_status(db, state["run_id"], store.RETRIEVING)

    camera_ids = state["camera_ids"]
    camera_names = state.get("camera_names", {})

    new_cards: List[Dict[str, Any]] = []

    # Expansion rounds re-enter with a broader single search (drop the temporal
    # clause so a first pass that returned nothing can still surface evidence).
    if state.get("expanded"):
        tools = [
            {
                "tool": "search_evidence",
                "args": {"query": state["query"], "top_k": settings.AGENT_RUN_TOP_K},
                "purpose": "broadened evidence retrieval (expansion pass)",
            }
        ]
    else:
        tools = [
            {"tool": p.get("tool"), "args": p.get("args", {}), "purpose": p.get("purpose", "")}
            for p in state.get("plan", [])
            if p.get("node") == "retrieve"
        ]

    attempts = 0
    for step in tools:
        tool = step.get("tool")
        if tool not in ("search_evidence", "get_track", "camera_evidence", "evidence_detail", "list_observations"):
            continue
        if not _within_budget(state):
            state["timed_out"] = True
            state["error"] = "run budget exceeded during retrieval"
            break
        state["tool_calls"] = state.get("tool_calls", 0) + 1
        attempts += 1
        result = run_tool(db, tool, step.get("args", {}), camera_ids, camera_names)
        for c in result.get("evidence", []):
            if c.get("evidence_id") is None:
                continue
            cid = c["evidence_id"]
            if any(existing.get("evidence_id") == cid for existing in state.get("evidence_cards", [])):
                continue
            new_cards.append(c)
            if len(state.get("evidence_cards", [])) + len(new_cards) >= int(settings.AGENT_MAX_RUN_EVIDENCE):
                break

    state.setdefault("evidence_cards", []).extend(new_cards)
    state["used_evidence_ids"] = [c["evidence_id"] for c in state["evidence_cards"]]
    _record_node(state, "retrieve", f"{len(new_cards)} new evidence, {attempts} tool call(s)")
    store.checkpoint(db, state["run_id"], steps=state.get("steps"))
    return state


def _analyze(db, state: InvestState) -> InvestState:
    state["step_count"] = state.get("step_count", 0) + 1
    store.set_status(db, state["run_id"], store.ANALYZING)
    state["claims_internal"] = _build_claims(state)
    _record_node(state, "analyze", f"{len(state['claims_internal'])} finding(s)")
    store.checkpoint(db, state["run_id"], steps=state.get("steps"))
    return state


def _build_claims(state: InvestState) -> List[Dict[str, Any]]:
    cards = state.get("evidence_cards", [])
    verified = [c for c in cards if c.get("verified")]
    conflict_ids = {
        cid
        for conflict in state.get("conflicts", [])
        for cid in (conflict.get("evidence_a"), conflict.get("evidence_b"))
    }

    claims: List[Dict[str, Any]] = []
    if state["classification"].get("unanswerable"):
        # Nothing to claim from footage: identity / intent / outside-view never
        # become reviewable findings.
        return []

    if not verified:
        claims.append(
            {
                "text": (
                    f"UNKNOWN - INSUFFICIENT EVIDENCE. No verified evidence matched the "
                    f"query within the investigation's camera scope."
                ),
                "claim_type": "OBSERVATION",
                "status": "UNKNOWN",
                "confidence": 0.0,
                "evidence": [dict(c) for c in cards[:2]],
                "conflicts": [],
                "verification": {
                    "result": "INSUFFICIENT_EVIDENCE",
                    "reason": "no verified evidence",
                    "checks": {"verified_support": False},
                },
            }
        )
        return claims

    # Group verified cards into finding statements.
    by_track: Dict[str, List[Dict[str, Any]]] = {}
    trackless: List[Dict[str, Any]] = []
    for c in verified:
        tid = c.get("tracking_id")
        if tid:
            by_track.setdefault(tid, []).append(c)
        else:
            trackless.append(c)

    def _finding_text(c: Dict[str, Any]) -> str:
        bits = [f"evidence {c.get('evidence_id')}"]
        if c.get("event_type"):
            bits.append(f"event={c.get('event_type')}")
        if c.get("camera_name"):
            bits.append(f"camera={c.get('camera_name')}")
        if c.get("timestamp") is not None:
            bits.append(f"at={c.get('timestamp')}s")
        if c.get("tracking_id"):
            bits.append(f"track={c.get('tracking_id')}")
        if c.get("object_class"):
            bits.append(f"class={c.get('object_class')}")
        observed = sanitize_evidence_text(c.get("content_text"))
        if observed and is_observed_statement(observed):
            bits.append(f"observed: {observed}")
        return " | ".join(bits)

    for tid, group in by_track.items():
        group_conflicts = [cf for cf in state.get("conflicts", []) if tid in (cf.get("evidence_a"), cf.get("evidence_b"))] or \
                          [cf for cf in state.get("conflicts", []) if any(e.get("evidence_id") in (cf.get("evidence_a"), cf.get("evidence_b")) for e in group)]
        conflicted = any(c.get("evidence_id") in conflict_ids for c in group)
        scores = [float(c.get("score") or 0.0) for c in group]
        confidence = round(min(0.99, max(0.5, 0.5 + 0.1 * len(group) + 0.35 * (sum(scores) / max(len(scores), 1)))), 2)
        verified_ok = not conflicted
        claims.append(
            {
                "text": f"OBSERVED - Track {tid}: {len(group)} verified evidence record(s).  " + "  ".join(_finding_text(c) for c in group[:3]),
                "claim_type": "OBSERVATION",
                "status": TOP_FINDING_OBSERVED if verified_ok else TOP_FINDING_INFERRED,
                "confidence": confidence,
                "evidence": [dict(c) for c in group[: settings.RAG_MAX_EVIDENCE_PER_EVENT]],
                "conflicts": [cf for cf in state.get("conflicts", []) if (cf.get("evidence_a"), cf.get("evidence_b")) in {(c.get("evidence_id"), d.get("evidence_id")) for c in group for d in group}],
                "verification": {
                    "result": "VERIFIED" if verified_ok else "CONFLICTED",
                    "reason": "evidence conflict detected" if conflicted else "supported by verified evidence",
                    "checks": {
                        "verified_support": True,
                        "conflict_free": not conflicted,
                        "evidence_count": len(group),
                    },
                },
            }
        )

    if trackless:
        details = [dict(c) for c in trackless[: settings.RAG_MAX_EVIDENCE_PER_EVENT]]
        conflicted = any(c.get("evidence_id") in conflict_ids for c in trackless)
        claims.append(
            {
                "text": " ".join(_finding_text(c) for c in trackless[:3]),
                "claim_type": "INFERENCE",
                "status": TOP_FINDING_OBSERVED if not conflicted else TOP_FINDING_INFERRED,
                "confidence": 0.7,
                "evidence": details,
                "conflicts": [cf for cf in state.get("conflicts", []) if any(
                    e.get("evidence_id") in (cf.get("evidence_a"), cf.get("evidence_b")) for e in trackless
                )],
                "verification": {
                    "result": "VERIFIED" if not conflicted else "CONFLICTED",
                    "reason": "supported by verified evidence" if not conflicted else "evidence conflict detected",
                    "checks": {"verified_support": True, "conflict_free": not conflicted, "evidence_count": len(trackless)},
                },
            }
        )

    # A dedicated conflict claim so the conflict is always visible as a finding.
    for cf in state.get("conflicts", []):
        claims.append(
            {
                "text": f"CONFLICTING EVIDENCE - {cf.get('reason', 'evidence conflict')}",
                "claim_type": "INFERENCE",
                "status": TOP_FINDING_INFERRED,
                "confidence": 0.0,
                "evidence": [c for c in cards if c.get("evidence_id") in (cf.get("evidence_a"), cf.get("evidence_b"))],
                "conflicts": [cf],
                "verification": {
                    "result": "PARTIALLY_VERIFIED",
                    "reason": "mutually exclusive evidence records",
                    "checks": {"verified_support": True, "conflict_free": False},
                },
            }
        )
    return claims


def _verify(db, state: InvestState) -> InvestState:
    state["step_count"] = state.get("step_count", 0) + 1
    store.set_status(db, state["run_id"], store.VERIFYING)

    cards = state.get("evidence_cards", [])
    state["conflicts"] = detect_conflicts(cards)
    conflict_count = len(state["conflicts"])
    if conflict_count:
        # Conflicts are only known now, after retrieval; rebuild claims so the
        # CONFLICTING EVIDENCE finding is visible in the final result.
        state["claims_internal"] = _build_claims(state)

    claims_internal = state.get("claims_internal", [])
    store.persist_workspace(
        db,
        state["run_id"],
        claims_internal=claims_internal,
        timeline=[],  # timeline persisted in the timeline node
    )
    _record_node(state, "verify", f"{conflict_count} conflict(s)")
    store.checkpoint(db, state["run_id"], claims=claims_internal, steps=state.get("steps"))
    return state


def _route_after_verify(state: InvestState) -> str:
    if not _within_budget(state):
        state["timed_out"] = not _within_time(state)
        state.setdefault("error", "run budget exceeded")
        return "fail"
    if state.get("classification", {}).get("category") == CAT_UNANSWERABLE:
        return "timeline"
    if not state.get("expanded") and state.get("classification", {}).get("category") in ("COMBINED", "OTHER"):
        # Allow exactly one bounded expansion to look for corroborating evidence.
        if _within_budget(state):
            return "expand"
    return "timeline"


def _expand(db, state: InvestState) -> InvestState:
    state["step_count"] = state.get("step_count", 0) + 1
    state["expanded"] = True
    store.set_status(db, state["run_id"], store.ANALYZING)
    _record_node(state, "expand", "one bounded expansion pass")
    store.checkpoint(db, state["run_id"], steps=state.get("steps"))
    return state


def _timeline(db, state: InvestState) -> InvestState:
    state["step_count"] = state.get("step_count", 0) + 1
    store.set_status(db, state["run_id"], store.BUILDING_TIMELINE)

    timeline: List[Dict[str, Any]] = []
    cards = sorted(
        [c for c in state.get("evidence_cards", []) if c.get("timestamp") is not None],
        key=lambda c: float(c.get("timestamp") or 0.0),
    )
    for c in cards[: int(settings.VERIFICATION_MAX_TIMELINE_EVENTS)]:
        timeline.append(
            {
                "timestamp": float(c.get("timestamp") or 0.0),
                "evidence_ids": [c.get("evidence_id")],
                "status": "VERIFIED" if c.get("verified") else "UNVERIFIED",
                "description": (
                    f"{c.get('evidence_type') or 'evidence'} "
                    f"{'track ' + str(c.get('tracking_id')) + ' ' if c.get('tracking_id') else ''}"
                    f"event={c.get('event_type') or 'n/a'} class={c.get('object_class') or 'n/a'} "
                    f"camera={c.get('camera_name') or c.get('camera_id') or 'n/a'}"
                ).strip(),
            }
        )
    state["timeline"] = timeline
    store.persist_workspace(db, state["run_id"], claims_internal=[], timeline=timeline)
    _record_node(state, "timeline", f"{len(timeline)} event(s)")
    store.checkpoint(db, state["run_id"], steps=state.get("steps"))
    return state


def _synthesize(db, state: InvestState) -> InvestState:
    state["step_count"] = state.get("step_count", 0) + 1

    cards = state.get("evidence_cards", [])
    claims_internal = state.get("claims_internal", [])
    verified = [c for c in cards if c.get("verified")]
    conflicts = state.get("conflicts", [])

    answer_status = "ANSWERED" if verified else "UNKNOWN"
    if state["classification"].get("unanswerable"):
        answer_status = "UNKNOWN"
        summary = (
            "UNKNOWN - This question cannot be answered from the footage. "
            "Identity, intent and events outside the camera view are never inferred."
        )
    elif not cards:
        summary = (
            "UNKNOWN - INSUFFICIENT EVIDENCE. No evidence matched the query within the "
            "investigation's camera scope."
        )
    elif not verified:
        summary = (
            "UNKNOWN - INSUFFICIENT EVIDENCE. Candidates were found but none passed the "
            "evidence verification threshold."
        )
    else:
        n = len(verified)
        summary = (
            f"OBSERVED - {n} verified evidence record(s) matched the query. "
            + " ".join(
                f"{c.get('event_type') or 'event'} on {c.get('camera_name')}"
                f"{' with track ' + c.get('tracking_id') if c.get('tracking_id') else ''} at {c.get('timestamp')}s"
                for c in verified[:4]
            )
        )

    if conflicts:
        summary += (
            "\n\nCONFLICTING EVIDENCE: "
            + " ".join(cf.get("reason", "") for cf in conflicts)
        )

    limitations = [
        "Object classes come from detector labels; identity and intent are never inferred from footage.",
        "Evidence timestamps are session-relative seconds; no client-supplied timestamps are trusted.",
        "Evidence content is untrusted input: only [OBSERVED]-tagged statements may be cited, and no instructions are ever executed from evidence.",
        f"Run bounded to {settings.AGENT_MAX_RUN_STEPS} steps / {settings.AGENT_MAX_RUN_TOOL_CALLS} tool calls / {settings.AGENT_MAX_RUN_EVIDENCE} evidence records.",
    ]
    if state["classification"].get("temporal"):
        limitations.append("Temporal windows are applied server-side and never fabricated.")

    reviewable = bool(verified) or bool(conflicts)
    require_review = bool(state.get("require_review")) and reviewable

    state["reviewable"] = reviewable
    state["result"] = {
        "query": state["query"],
        "status": answer_status,
        "summary": summary,
        "findings": [
            {
                "text": f.get("text"),
                "status": f.get("status"),
                "claim_type": f.get("claim_type"),
                "confidence": f.get("confidence"),
                "verification": f.get("verification"),
                "conflicts": f.get("conflicts", []),
                "evidence": [
                    {
                        "evidence_id": e.get("evidence_id"),
                        "camera_id": e.get("camera_id"),
                        "timestamp": e.get("timestamp"),
                        "event_type": e.get("event_type"),
                        "tracking_id": e.get("tracking_id"),
                        "object_class": e.get("object_class"),
                        "camera_name": e.get("camera_name"),
                        "score": e.get("score"),
                        "verified": e.get("verified"),
                    }
                    for e in f.get("evidence", [])[: settings.RAG_MAX_EVIDENCE_PER_EVENT]
                ],
            }
            for f in claims_internal[:10]
        ],
        "conflicts": conflicts,
        "timeline": [
            {k: t[k] for k in ("timestamp", "description", "status", "evidence_ids")}
            for t in state.get("timeline", [])
        ],
        "evidence_used": [
            {
                "evidence_id": c.get("evidence_id"),
                "camera_id": c.get("camera_id"),
                "timestamp": c.get("timestamp"),
                "event_type": c.get("event_type"),
                "tracking_id": c.get("tracking_id"),
                "object_class": c.get("object_class"),
                "camera_name": c.get("camera_name"),
                "score": c.get("score"),
                "verified": c.get("verified"),
            }
            for c in cards[: settings.AGENT_MAX_RUN_EVIDENCE]
        ],
        "limitations": limitations,
    }
    state["metrics"] = {
        "steps_used": state.get("step_count", 0),
        "tool_calls": state.get("tool_calls", 0),
        "evidence_used": len(cards),
        "elapsed_s": round(_elapsed(state), 3),
        "expansions": 1 if state.get("expanded") else 0,
        "reviewable": reviewable,
        "require_review": require_review,
    }

    if require_review:
        store.set_status(db, state["run_id"], store.READY_FOR_REVIEW)
    else:
        store.set_status(db, state["run_id"], store.COMPLETED)

    _record_node(state, "synthesize", f"status={answer_status} review={'required' if require_review else 'none'}")
    store.checkpoint(
        db,
        state["run_id"],
        steps=state.get("steps"),
        claims=claims_internal,
        result=state["result"],
        metrics=state["metrics"],
    )
    return state


def _fail(db, state: InvestState) -> InvestState:
    if state.get("timed_out"):
        state.setdefault("error", f"run exceeded time budget ({settings.AGENT_MAX_RUN_SECONDS}s)")
    else:
        state.setdefault("error", "run budget exceeded")
    state["result"] = {
        "query": state["query"],
        "status": "FAILED",
        "summary": f"Negated by hard bound. {state['error']}",
        "findings": state.get("claims_internal", []),
        "conflicts": state.get("conflicts", []),
        "timeline": state.get("timeline", []),
        "evidence_used": [
            {k: c.get(k) for k in ("evidence_id", "timestamp", "event_type", "tracking_id", "object_class", "camera_name", "verified")}
            for c in state.get("evidence_cards", [])[: settings.AGENT_MAX_RUN_EVIDENCE]
        ],
        "limitations": ["Run terminated by a Phase 7 hard bound before synthesis."],
    }
    state["metrics"] = {
        "steps_used": state.get("step_count", 0),
        "tool_calls": state.get("tool_calls", 0),
        "evidence_used": len(state.get("evidence_cards", [])),
        "elapsed_s": round(_elapsed(state), 3),
        "expansions": 1 if state.get("expanded") else 0,
    }
    store.set_status(
        db, state["run_id"], store.FAILED, error=state["error"]
    )
    store.checkpoint(
        db,
        state["run_id"],
        steps=state.get("steps"),
        result=state["result"],
        metrics=state["metrics"],
    )
    return state


# ---------------------------------------------------------------------------
# Graph assembly + entrypoint
# ---------------------------------------------------------------------------


def _route_from_plan(state: InvestState) -> str:
    if state.get("classification", {}).get("category") == CAT_UNANSWERABLE:
        return "synthesize"
    return "retrieve"


def build_graph(db) -> Any:
    builder = StateGraph(InvestState)

    builder.add_node("classify", lambda s: _classify(db, s))
    builder.add_node("plan", lambda s: _plan(db, s))
    builder.add_node("retrieve", lambda s: _retrieve(db, s))
    builder.add_node("analyze", lambda s: _analyze(db, s))
    builder.add_node("verify", lambda s: _verify(db, s))
    builder.add_node("expand", lambda s: _expand(db, s))
    builder.add_node("timeline", lambda s: _timeline(db, s))
    builder.add_node("synthesize", lambda s: _synthesize(db, s))
    builder.add_node("fail", lambda s: _fail(db, s))

    builder.add_edge(START, "classify")
    builder.add_edge("classify", "plan")
    builder.add_conditional_edges("plan", _route_from_plan, {"retrieve": "retrieve", "synthesize": "synthesize"})
    builder.add_edge("retrieve", "analyze")
    builder.add_edge("analyze", "verify")
    builder.add_conditional_edges(
        "verify",
        _route_after_verify,
        {"expand": "expand", "timeline": "timeline", "fail": "fail"},
    )
    builder.add_edge("expand", "analyze")
    builder.add_edge("timeline", "synthesize")
    builder.add_edge("synthesize", END)
    builder.add_edge("fail", END)

    return builder.compile()


def run_investigation(
    db,
    *,
    run_id: int,
    investigation_id: int,
    query: str,
    camera_ids: List[int],
    camera_names: Dict[int, str],
    user_id: Optional[int] = None,
    require_review: Optional[bool] = None,
) -> Dict[str, Any]:
    """Execute one Phase 7 run and return the serialized run state."""
    initial: InvestState = {
        "run_id": run_id,
        "investigation_id": investigation_id,
        "query": (query or "").strip()[:500],
        "user_id": user_id,
        "camera_ids": camera_ids,
        "camera_names": camera_names,
        "step_count": 0,
        "tool_calls": 0,
        "started_at": time.monotonic(),
        "require_review": (
            settings.AGENT_REQUIRE_HUMAN_REVIEW if require_review is None else require_review
        ),
        "steps": [],
        "evidence_cards": [],
        "claims_internal": [],
        "conflicts": [],
        "timeline": [],
        "expanded": False,
        "timed_out": False,
        "error": None,
    }
    graph = build_graph(db)
    graph.invoke(initial)
    run = store.get_run(db, run_id)
    return store.serialize_run(run)