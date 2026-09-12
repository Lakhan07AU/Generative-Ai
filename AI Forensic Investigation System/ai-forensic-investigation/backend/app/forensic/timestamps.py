"""Phase 8 forensic timestamp normalisation.

All event times are normalised to server-provided absolute frame/buffer
timestamps (seconds). VLM processing time is never used as the event time.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def normalize_timestamp(value: Any) -> Optional[float]:
    """Normalise a frame/buffer timestamp to a float of seconds (or None)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        return ts if ts >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        try:
            return float(text)
        except ValueError:
            m = re.match(r"^\s*(\d+)(?:\.(\d+))?\s*$", text)
            return float(text) if m else None
    return None


def format_hhmmss(seconds: Optional[float]) -> str:
    """Format seconds-of-day as HH:MM:SS (UTC-clamped), else 'unknown time'."""
    if seconds is None:
        return "unknown time"
    total = max(0, int(round(seconds)))
    total %= 86400
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def event_time_of(row) -> Optional[float]:
    """The time an event is believed to have occurred.

    Priority: explicit frame_timestamp -> VLM window_start -> capture clock.
    A VLM analysis time is never used as the event time.
    """
    if getattr(row, "frame_timestamp", None) is not None:
        ts = normalize_timestamp(row.frame_timestamp)
        if ts is not None:
            return ts
    if getattr(row, "window_start", None) is not None:
        ts = normalize_timestamp(row.window_start)
        if ts is not None:
            return ts
    if getattr(row, "window_end", None) is not None:
        ts = normalize_timestamp(row.window_end)
        if ts is not None:
            return ts
    if getattr(row, "captured_at", None) is not None:
        ts = normalize_timestamp(row.captured_at)
        if ts is not None:
            return ts
    if getattr(row, "created_at", None) is not None:
        return row.created_at.timestamp()
    return None


def event_end_of(row) -> Optional[float]:
    """Optional end time of an event (VLM window_end, else None)."""
    if getattr(row, "window_end", None) is not None:
        ts = normalize_timestamp(row.window_end)
        if ts is not None:
            return ts
    return None


def analysis_time_of(row) -> Optional[datetime]:
    """When the evidence/observation was analysed (capture or created clock)."""
    for attr in ("captured_at", "created_at"):
        value = getattr(row, attr, None)
        if isinstance(value, datetime):
            return value
    return None


def storage_time_of(row) -> Optional[datetime]:
    """When the evidence was durably stored (created_at)."""
    value = getattr(row, "created_at", None)
    return value if isinstance(value, datetime) else None


def normalize_metadata(row) -> Dict[str, Any]:
    raw = {}
    for attr in ("extra_metadata", "metadata"):
        value = getattr(row, attr, None)
        if isinstance(value, dict) and value:
            raw = dict(value)
            break
    return raw


def resolution_of(row) -> Optional[Dict[str, int]]:
    """Extract {width, height} pixel dimensions from metadata or content text."""
    meta = normalize_metadata(row)
    width = meta.get("width") or meta.get("frame_width")
    height = meta.get("height") or meta.get("frame_height")
    for key in ("width", "height"):
        value = meta.get(key)
        if value in (None, ""):
            continue
        try:
            num = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if key == "width" and num > 0:
            width = num
        if key == "height" and num > 0:
            height = num
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        return {"width": width, "height": height}
    text = str(getattr(row, "content_text", "") or "")
    m = re.search(r"(\d{2,5})\s*[xX×]\s*(\d{2,5})", text)
    if m:
        return {"width": int(m.group(1)), "height": int(m.group(2))}
    return None