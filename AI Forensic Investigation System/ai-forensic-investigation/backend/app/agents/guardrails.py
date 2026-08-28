"""Agent guardrails (Part 3).

Encodes the hard safety boundaries for the bounded investigation agent:

Budgets:
  * maximum tool calls
  * maximum investigation steps
  * per-tool call timeout
  * retry limit

Forbidden behaviours:
  * modify original evidence
  * approve reports
  * identify real-world people
  * invent timestamps
  * invent policies
  * create unsupported claims
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.core.config import settings

# The only tools the investigation agent may ever invoke. Anything else is
# rejected up-front as "invalid tool" - this also covers attempted access to
# tools that would mutate evidence or approve reports.
ALLOWED_TOOLS = frozenset(
    {
        "search_video",
        "search_person",
        "search_object",
        "search_event",
        "get_clip",
        "get_frame",
        "search_policy",
        "build_timeline",
        "verify_evidence",
    }
)

FORBIDDEN_ACTIONS = (
    "The agent may not modify, delete or overwrite original evidence.",
    "The agent may not approve or sign off reports.",
    "The agent may not attribute identity to real-world people; subjects are "
    "referred to only by tracking identifiers.",
    "The agent may not invent timestamps; every timestamp must come from a "
    "source clip/frame within the authoritative video bounds.",
    "The agent may not invent policies; policy text must be retrieved verbatim.",
    "The agent may not create unsupported claims; every claim must map to "
    "retrieved evidence or be marked INSUFFICIENT_EVIDENCE.",
)

FORBIDDEN_REASONS = {
    "modify_evidence": "original evidence is immutable",
    "delete_evidence": "original evidence is immutable",
    "approve_report": "agent cannot approve reports",
    "identify_person": "agent must not identify real-world people",
}


class GuardrailViolation(RuntimeError):
    """Raised when the agent attempts a disallowed action."""


class BudgetExceeded(RuntimeError):
    """Raised when a budget (tool calls / steps / retries) is exceeded."""


class ToolTimeout(RuntimeError):
    """Raised when a tool call exceeds its per-call deadline."""


@dataclass
class Budget:
    """Tracks and enforces the bounded-investigation budgets."""

    max_tool_calls: int = field(default_factory=lambda: settings.AGENT_MAX_TOOL_CALLS)
    max_steps: int = field(default_factory=lambda: settings.AGENT_MAX_STEPS)
    timeout_seconds: float = field(
        default_factory=lambda: settings.AGENT_TOOL_TIMEOUT_SECONDS
    )
    retry_limit: int = field(default_factory=lambda: settings.AGENT_RETRY_LIMIT)

    tool_calls: int = 0
    steps: int = 0
    retries: int = 0
    start_time: float = field(default_factory=time.monotonic)

    def remaining_tool_calls(self) -> int:
        return max(0, self.max_tool_calls - self.tool_calls)

    def remaining_steps(self) -> int:
        return max(0, self.max_steps - self.steps)

    def enter_step(self) -> None:
        self.steps += 1
        if self.steps > self.max_steps:
            raise BudgetExceeded(f"maximum investigation steps ({self.max_steps}) exceeded")

    def enter_tool_call(self) -> None:
        self.tool_calls += 1
        if self.tool_calls > self.max_tool_calls:
            raise BudgetExceeded(f"maximum tool calls ({self.max_tool_calls}) exceeded")

    def now(self) -> float:
        return time.monotonic()

    def deadline(self) -> float:
        return self.now() + self.timeout_seconds

    def is_expired(self, start_deadline: float) -> bool:
        return self.now() > start_deadline

    def register_retry(self) -> None:
        self.retries += 1
        if self.retries > self.retry_limit:
            raise BudgetExceeded(f"retry limit ({self.retry_limit}) exceeded")


def assert_allowed_tool(name: str) -> None:
    """Reject any tool outside the allowlist (invalid-tool guard)."""
    if name not in ALLOWED_TOOLS:
        raise GuardrailViolation(f"disallowed/unknown tool '{name}'")


def validate_timestamp(timestamp: float | None, video_start: float | None, video_end: float | None) -> bool:
    """Timestamp validation: never trust an LLM-generated timestamp.

    A timestamp is authoritative only if it falls within the source video's
    recorded bounds (when known).
    """
    if timestamp is None:
        return False
    if video_start is not None and timestamp < video_start:
        return False
    if video_end is not None and timestamp > video_end:
        return False
    return True
