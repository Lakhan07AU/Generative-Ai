"""VLM trigger rules (Phase 4).

Decides WHICH tracking events may trigger an observation. Bounded by
configuration (``VLM_EVENT_TRIGGERS``) so an event storm never opens a request
flood; the per-session rate limiter provides the hard backstop.
"""

from __future__ import annotations

from typing import Iterable, Optional, Set

from app.core.config import settings


def event_triggers_set(enabled: Optional[bool] = None) -> Set[str]:
    """Resolve the configured set of triggering event types."""
    if enabled is None:
        enabled = bool(getattr(settings, "VLM_ENABLE_EVENT_TRIGGERS", True))
    if not enabled:
        return set()
    raw = getattr(settings, "VLM_EVENT_TRIGGERS", "")
    return {t.strip() for t in raw.split(",") if t.strip()}


def is_trigger_event(event_type: str, enabled: Optional[bool] = None) -> bool:
    if not event_type:
        return False
    return event_type in event_triggers_set(enabled=enabled)


def periodic_interval_seconds() -> float:
    return float(getattr(settings, "VLM_PERIODIC_SECONDS", 0.0) or 0.0)