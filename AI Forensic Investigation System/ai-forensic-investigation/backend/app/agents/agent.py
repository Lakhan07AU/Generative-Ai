"""Bounded LangGraph investigation agent (Part 3).

A single agent built with LangGraph's StateGraph implementing:

    User Query
      -> Query Understanding
      -> Tool Selection
      -> Retrieve Evidence
      -> Reason
      -> Verify
      -> Grounded Answer

Guardrails (budgets, timeouts, retries, forbidden actions, validated
timestamps, verbatim policy) are enforced inline. Every tool call is logged to
the audit trail.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.database import models
from app.ai import provider
from app.agents import planner
from app.agents.tools import get_tool
from app.agents.guardrails import (
    ALLOWED_TOOLS,
    Budget,
    GuardrailViolation,
    assert_allowed_tool,
)
from app.audit.service import (
    log_agent_invocation,
    log_timeline_generation,
    log_tool_call,
    log_verification,
)
from app.verification import service as verification_service
from app.timeline import builder as timeline_builder

logger = logging.getLogger(__name__)

VERIFIER_VERSION = verification_service.VERIFIER_VERSION


class AgentState(TypedDict, total=False):
    query: str
    video_id: Optional[int]
    user_id: Optional[int]
    investigation_id: Optional[int]
    analysis: dict
    plan: list[dict]
    plan_index: int
    tool_calls: list[dict]
    evidence: list[dict]
    results: dict
    step_count: int
    tool_call_count: int
    retry_count: int
    claims: list[dict]
    timeline: list[dict]
    policy_sections: list[dict]
    answer: str
    grounded: bool
    done: bool
    error: Optional[str]


def _tool_call_summary(name: str, args: dict, result: Any, status: str) -> dict:
    """Build an audit-safe record for a tool call."""
    return {
        "name": name,
        "arguments": {k: v for k, v in args.items() if k not in ("query", "claim_text", "label")},
        "status": status,
        "summary": _compact(result),
    }


def _compact(result: Any) -> dict:
    if isinstance(result, dict):
        out = {}
        for k in ("status", "result", "count", "evidence_id", "clip_public_id", "found"):
            if k in result:
                out[k] = result[k]
        if "events" in result and isinstance(result["events"], list):
            out["events"] = len(result["events"])
        return out
    if isinstance(result, list):
        return {"count": len(result)}
    return {}


def _invoke_tool(db, budget: Budget, name: str, args: dict) -> tuple[Any, str]:
    """Invoke one tool with guardrails: allowlist, per-call timeout, retries."""
    assert_allowed_tool(name)
    tool = get_tool(name)
    if tool is None:
        raise GuardrailViolation(f"unknown tool '{name}'")

    deadline = budget.deadline()
    last_err: Optional[Exception] = None
    for attempt in range(budget.retry_limit + 1):
        if budget.is_expired(deadline):
            return None, "timeout"
        try:
            result = tool.invoke(db, args)
            return result, "ok"
        except (ValueError, GuardrailViolation) as exc:
            # Argument/guard errors are not retried - fail fast.
            return None, f"error:{exc}"
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            budget.register_retry()
            logger.warning("tool '%s' failed (attempt %d): %s", name, attempt + 1, exc)
            time.sleep(0.01)
    return None, f"error:{last_err}"


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def _understand(db, state: AgentState) -> AgentState:
    from app.rag.video_rag import analyze_query

    query = state["query"]
    analysis = analyze_query(query)
    plan = planner.build_plan(db, query, state.get("video_id"))
    plan = planner.refine_with_llm(query, plan)
    return {
        **state,
        "analysis": analysis,
        "plan": plan,
        "plan_index": 0,
        "tool_calls": [],
        "evidence": [],
        "results": {},
        "step_count": 0,
        "tool_call_count": 0,
        "retry_count": 0,
        "claims": [],
        "timeline": [],
        "policy_sections": [],
        "done": False,
    }


def _run_tool(db, budget: Budget, state: AgentState) -> AgentState:
    plan = state.get("plan", [])
    plan_index = state.get("plan_index", 0)
    # Skip any step that exceeded budgets.
    budget.enter_step()
    budget.enter_tool_call()

    if plan_index >= len(plan):
        return {**state, "done": True}

    invocation = plan[plan_index]
    name = invocation["tool"]
    args = invocation.get("arguments", {})
    result, status = _invoke_tool(db, budget, name, args)

    # Audit-log every tool call.
    investigation_id = state.get("investigation_id")
    user_id = state.get("user_id")
    if investigation_id:
        log_tool_call(
            db, investigation_id, user_id, name,
            args_summary=f"args={str({k: v for k, v in args.items() if k != 'query'})[:300]}",
            status=status,
        )

    tool_record = _tool_call_summary(name, args, result, status)
    tool_calls = state.get("tool_calls", []) + [tool_record]
    results = dict(state.get("results", {}))
    results.setdefault(name, [])
    results[name].append(result)

    # Harvest evidence references from common result shapes.
    evidence = list(state.get("evidence", []))
    evidence.extend(_harvest_evidence(result))

    new_state = {
        **state,
        "plan_index": plan_index + 1,
        "tool_calls": tool_calls,
        "results": results,
        "evidence": evidence,
        "step_count": state.get("step_count", 0) + 1,
        "tool_call_count": state.get("tool_call_count", 0) + 1,
        "retry_count": budget.retries,
    }
    # Stop early if the next step would exceed budgets.
    if plan_index + 1 >= len(plan) or budget.remaining_tool_calls() <= 0 or budget.remaining_steps() <= 0:
        new_state["done"] = True
    return new_state


def _harvest_evidence(result: Any) -> list[dict]:
    """Pull evidence references (clip ids / evidence ids) out of a tool result."""
    refs: list[dict] = []
    if isinstance(result, dict):
        for key in ("evidence", "results", "frames"):
            val = result.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        ref = item.get("evidence_id") or (
                            f"E-{item.get('clip_id') if item.get('clip_id') is not None else 0:03d}"
                        )
                        clip = item.get("clip_public_id") or item.get("clip_id")
                        refs.append({
                            "evidence_id": ref,
                            "clip_public_id": clip,
                            "timestamp": item.get("timestamp") or item.get("start_time"),
                            "status": item.get("status"),
                        })
        for key in ("status", "result", "found", "evidence_id", "clip_public_id"):
            pass  # handled above
    return _dedupe(refs)


def _dedupe(refs: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for r in refs:
        k = r.get("evidence_id")
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _finalize(db, state: AgentState) -> AgentState:
    investigation_id = state.get("investigation_id")
    user_id = state.get("user_id")
    query = state["query"]
    results = state.get("results", {})
    evidence = state.get("evidence", [])

    policy_sections = list(state.get("policy_sections", []))
    # Harvest verbatim policy text from policy search results.
    for pr in results.get("search_policy", []):
        if isinstance(pr, dict) and pr.get("results"):
            for hit in pr["results"]:
                if isinstance(hit, dict) and hit.get("text"):
                    policy_sections.append(hit)

    # ---- Synthesize a verifiable claim from the top retrieved evidence -----
    claim = _synthesize_claim(query, results, evidence)
    claims: list[dict] = []
    verification_result = None
    if claim:
        vres = verification_service.verify_claim(
            db,
            claim_text=claim["claim_text"],
            investigation_id=investigation_id,
            video_id=state.get("video_id"),
            timestamp=claim.get("timestamp"),
            claim_type=claim.get("claim_type", "OBSERVATION"),
            persist=bool(investigation_id),
        )
        verification_result = vres
        claims.append(
            {
                "claim_text": vres["claim_text"],
                "claim_type": vres["claim_type"],
                "status": vres["result"],
                "result": vres["result"],
                "reason": vres["reason"],
                "verifier_version": vres["verifier_version"],
                "evidence": vres["evidence"],
            }
        )
        if investigation_id and "claim_id" in vres:
            log_verification(db, investigation_id, user_id, vres["claim_id"], vres["result"])

    # ---- Build + persist timeline ------------------------------------------
    timeline = timeline_builder.build_timeline(
        db,
        investigation_id=investigation_id,
        video_id=state.get("video_id"),
        limit=settings.VERIFICATION_MAX_TIMELINE_EVENTS,
    )
    if investigation_id:
        timeline_builder.persist_timeline(db, investigation_id, timeline)
        log_timeline_generation(db, investigation_id, user_id, len(timeline))

    # ---- Grounded answer ----------------------------------------------------
    answer, grounded = _synthesize_answer(query, claims, verification_result, evidence, results)

    return {
        **state,
        "done": True,
        "claims": claims,
        "timeline": timeline,
        "policy_sections": policy_sections,
        "answer": answer,
        "grounded": grounded,
    }


def _synthesize_claim(query: str, results: dict, evidence: list[dict]) -> Optional[dict]:
    """Build one verifiable claim from the strongest retrieved evidence.

    No claim is created unless concrete evidence was retrieved - the agent must
    never create an unsupported claim.
    """
    if not evidence:
        return None
    # Favour search_video / search_person / search_object outputs.
    for src in ("search_video", "search_person", "search_object", "search_event"):
        bucket = results.get(src) or []
        for res in bucket:
            items = res if isinstance(res, list) else (
                res.get("results") or (res.get("evidence") if isinstance(res, dict) else [])
            )
            if isinstance(items, list) and items:
                top = items[0] if isinstance(items[0], dict) else None
                if not top:
                    continue
                ts = top.get("timestamp") or top.get("start_time")
                subject = top.get("label") or (top.get("objects") or ["subject"])[0] if top.get("objects") else "subject"
                location = top.get("camera_name") or top.get("location_context") or "the monitored area"
                claim_text = f"Subject detected in {location}"
                return {
                    "claim_text": claim_text,
                    "timestamp": ts,
                    "claim_type": "OBSERVATION",
                }
    # Fallback: evidence exists but no strong subject was surfaced.
    return {
        "claim_text": "Evidence matching the query was observed and recorded",
        "timestamp": None,
        "claim_type": "INFERENCE",
    }


def _synthesize_answer(query, claims, verification_result, evidence, results) -> tuple[str, bool]:
    if claims and claims[0]["status"] == "VERIFIED":
        return (
            f"[VERIFIED] Claim supported by evidence.\n"
            f"Claim: {claims[0]['claim_text']}\n"
            f"Reason: {claims[0]['reason']}",
            True,
        )
    if claims and claims[0]["status"] == "PARTIALLY_VERIFIED":
        return (
            f"[PARTIALLY_VERIFIED] Only partial / conflicting supporting evidence.\n"
            f"Claim: {claims[0]['claim_text']}\n"
            f"Reason: {claims[0]['reason']}",
            False,
        )
    # INSUFFICIENT or no evidence
    if evidence:
        return (
            "UNKNOWN - INSUFFICIENT EVIDENCE. Some evidence was retrieved but it does not "
            "support a verified claim for this query. Refine the query or timeline.",
            False,
        )
    return (
        "UNKNOWN - INSUFFICIENT EVIDENCE. No video evidence was found for this query. "
        "No unsupported claim has been created.",
        False,
    )


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _router(db, budget: Budget) -> callable:
    def route(state: AgentState) -> str:
        if state.get("done"):
            return "finalize"
        if budget.remaining_tool_calls() <= 0 or budget.remaining_steps() <= 0:
            return "finalize"
        if state.get("plan_index", 0) >= len(state.get("plan", [])):
            return "finalize"
        return "run_tool"

    return route


def run_investigation(
    db,
    query: str,
    investigation_id: Optional[int] = None,
    user_id: Optional[int] = None,
    video_id: Optional[int] = None,
) -> dict:
    """Execute the bounded investigation agent for a user query."""
    log_agent_invocation(db, investigation_id, user_id, query) if investigation_id else None

    budget = Budget()
    state: AgentState = {
        "query": query,
        "investigation_id": investigation_id,
        "user_id": user_id,
        "video_id": video_id,
        "done": False,
    }

    graph = StateGraph(AgentState)
    graph.add_node("understand", lambda s: _understand(db, s))
    graph.add_node("run_tool", lambda s: _run_tool(db, budget, s))
    graph.add_node("finalize", lambda s: _finalize(db, s))
    graph.add_edge(START, "understand")
    graph.add_edge("understand", "run_tool")
    graph.add_conditional_edges("run_tool", _router(db, budget), {
        "run_tool": "run_tool",
        "finalize": "finalize",
    })
    graph.add_edge("finalize", END)
    app_graph = graph.compile()

    final_state = app_graph.invoke(state)

    return {
        "investigation_id": investigation_id,
        "query": query,
        "status": "ANSWERED" if final_state.get("grounded") else (
            "PARTIAL" if final_state.get("claims") else "UNKNOWN"
        ),
        "answer": final_state.get("answer", ""),
        "grounded": final_state.get("grounded", False),
        "tool_calls": final_state.get("tool_calls", []),
        "steps": [
            {"step": i + 1, "node": t["name"], "summary": t.get("summary", {})}
            for i, t in enumerate(final_state.get("tool_calls", []))
        ],
        "claims": final_state.get("claims", []),
        "events": final_state.get("timeline", []),
        "policy_sections": final_state.get("policy_sections", []),
        "error": final_state.get("error"),
    }
