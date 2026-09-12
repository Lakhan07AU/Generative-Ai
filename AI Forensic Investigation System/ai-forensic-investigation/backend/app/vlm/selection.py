"""Evidence frame selection for live VLM observations (Phase 4).

Selects the MINIMUM set of evidence frames required to ground an observation.
Every selected frame is tied to provenance (frame_id / sequence / timestamp).
The rolling buffer uses the buffer's own monotonic-ish clock; event payloads
carry the detection ``frame_id`` which equals the buffer ``sequence`` at the time
of sampling, so events are mapped back onto buffered frames by sequence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from app.live.rolling_buffer import FrameEntry, RollingFrameBuffer
from app.tracking.schemas import TrackingEvent

logger = logging.getLogger(__name__)

EVENT_WINDOW_BEFORE_SECONDS = 3.0
EVENT_WINDOW_AFTER_SECONDS = 0.5


@dataclass
class FrameSelection:
    frames: List[FrameEntry]
    window_start: Optional[float]
    window_end: Optional[float]

    def __bool__(self) -> bool:
        return bool(self.frames)


def sample_evenly(entries: List[FrameEntry], limit: int) -> List[FrameEntry]:
    """Pick up to ``limit`` frames spread evenly across ``entries`` (oldest first)."""
    if limit <= 0 or not entries:
        return []
    if len(entries) <= limit:
        return list(entries)
    step = (len(entries) - 1) / (limit - 1) if limit > 1 else 0.0
    picked = sorted({round(i * step) for i in range(limit)})
    return [entries[p] for p in picked]


def _entry_by_sequence(buffer: RollingFrameBuffer, sequence: int) -> Optional[FrameEntry]:
    for entry in buffer.snapshot():
        if entry.sequence == sequence:
            return entry
    return None


def select_for_event(
    buffer: RollingFrameBuffer,
    event: TrackingEvent,
    max_frames: int,
    window_before: float = EVENT_WINDOW_BEFORE_SECONDS,
    window_after: float = EVENT_WINDOW_AFTER_SECONDS,
) -> FrameSelection:
    """Select evidence frames around a tracking event.

    The event's ``frame_index`` is matched to the buffered frame sequence. When
    the target frame is no longer buffered, the most recent buffered frames are
    used instead so the observation can still be grounded in real footage.
    """
    target = _entry_by_sequence(buffer, event.frame_index) if event.frame_index else None
    if target is None:
        latest = buffer.latest()
        if latest is None:
            return FrameSelection(frames=[], window_start=None, window_end=None)
        # Only a tiny look-back is honest here: no windowed history survived.
        entries = buffer.snapshot(limit=max_frames)
        return FrameSelection(
            frames=sample_evenly(entries, max_frames),
            window_start=entries[0].timestamp if entries else None,
            window_end=latest.timestamp,
        )
    start_ts = target.timestamp - window_before
    end_ts = target.timestamp + window_after
    candidates = buffer.frames_between(start_ts, end_ts)
    if not candidates:
        candidates = [target]
    frames = sample_evenly(candidates, max_frames)
    # Always keep the exact trigger frame when it survived the even sampling.
    if target not in frames:
        frames = frames + [target]
        frames = sample_evenly(frames, max_frames)
    return FrameSelection(
        frames=frames,
        window_start=min((f.timestamp for f in frames), default=None),
        window_end=max((f.timestamp for f in frames), default=None),
    )


def select_latest(buffer: RollingFrameBuffer, max_frames: int) -> FrameSelection:
    """Select the most recent buffered frames (manual / periodic triggers)."""
    if max_frames <= 0 or buffer.count() == 0:
        return FrameSelection(frames=[], window_start=None, window_end=None)
    entries = buffer.snapshot(limit=max_frames)
    return FrameSelection(
        frames=entries,
        window_start=entries[0].timestamp if entries else None,
        window_end=entries[-1].timestamp if entries else None,
    )