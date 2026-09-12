"""Phase 8 temporal sequencing of forensic timeline entries.

Relationships describe temporal order only (BEFORE / AFTER / DURING /
OVERLAPPING / NEAR) and always carry a causal-safety note: temporal order does
not establish causation.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.forensic import semantics


def _interval(entry) -> tuple:
    start = entry.get("timestamp")
    end = entry.get("end_timestamp")
    if end is None or end < start:
        end = start
    return start, end


def sequence_entries(entries: List[Dict[str, Any]], *, epsilon: float = 2.0, near_seconds: float = 5.0) -> List[Dict[str, Any]]:
    relationships: List[Dict[str, Any]] = []
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a = entries[i]
            b = entries[j]
            a_start, a_end = _interval(a)
            b_start, b_end = _interval(b)
            if a_start is None or b_start is None:
                continue

            label = None
            reason = ""
            if a_end < b_start - epsilon:
                label = "BEFORE"
                reason = f"{a['timeline_event_id']} ends before {b['timeline_event_id']} begins."
            elif b_end < a_start - epsilon:
                label = "AFTER"
                reason = f"{a['timeline_event_id']} begins after {b['timeline_event_id']} ends."
            elif a_start <= b_start and b_end <= a_end:
                label = "DURING"
                reason = f"{b['timeline_event_id']} occurs during {a['timeline_event_id']}."
            elif b_start <= a_start and a_end <= b_end:
                label = "DURING"
                reason = f"{a['timeline_event_id']} occurs during {b['timeline_event_id']}."
            else:
                label = "OVERLAPPING"
                reason = f"{a['timeline_event_id']} and {b['timeline_event_id']} occur at overlapping times."

            if label == "BEFORE" and (b_start - a_end) <= near_seconds:
                label = "NEAR"
                reason = f"{a['timeline_event_id']} and {b['timeline_event_id']} are close in time."

            relationships.append(
                {
                    "relationship": label,
                    "entry_a": a["timeline_event_id"],
                    "entry_b": b["timeline_event_id"],
                    "time_a": a_start,
                    "time_b": b_start,
                    "reason": reason,
                    "causal": False,
                    "causality_note": semantics.CAUSAL_NOTE,
                }
            )
    return relationships