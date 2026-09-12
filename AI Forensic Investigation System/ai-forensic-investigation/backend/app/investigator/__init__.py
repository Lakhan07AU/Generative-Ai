"""Phase 7 - Controlled investigation orchestration.

Deterministic, bounded, evidence-first agent over the Phase 6 forensic
retrieval stack, orchestrated as a LangGraph state machine. Every output the
agent produces (plan, tools calls, verifications, timeline, findings) is
inspectable and persisted to ``investigation_runs`` so a human can review it.

Pipeline per run:
    classify -> plan -> (retrieve -> analyze -> verify -> [expand]) ->
    timeline -> synthesize -> READY_FOR_REVIEW / COMPLETED

Guarantees:
    * evidence is only ever retrieved from the investigation's camera scope,
    * the graph is hard-bounded (steps / tool calls / evidence / wall time),
    * identity / intent / outside-view questions are never answered,
    * conflicting evidence is surfaced as CONFLICTING EVIDENCE, never resolved,
    * untrusted evidence text is never compiled into instructions or surfaced
      unless explicitly tagged [OBSERVED].
"""