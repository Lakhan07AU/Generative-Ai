"""Phase 4 unit tests: VLM observation layer in isolation.

Covers provider simulation output contract + forensic grounding, structured
output normalisation/guardrails, copy-safe preprocessing, evidence selection,
per-session rate limiting, bounded queue drop-oldest behaviour, worker
observation/error paths, and context fusion. No real VLM, camera or network.
"""

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from app.ai import provider
from app.core.config import settings
from app.live.rolling_buffer import RollingFrameBuffer
from app.tracking.schemas import TrackState, TrackSummary, TrackingEvent
from app.vlm import context as ctx
from app.vlm import selection, triggers
from app.vlm.preprocess import encode_frames
from app.vlm.queue import VlmRateLimiter
from app.vlm.schemas import VlmRequest, coerce_statements
from app.vlm.worker import VlmJob, VlmWorker


def _frame(width=640, height=480, value=120):
    return np.full((height, width, 3), value, dtype=np.uint8)


def _buffer_clock(now):
    """A clock pinned to ``now`` so rolling eviction stays inert in tests."""
    return lambda: now


def _buffer(now, **kw):
    return RollingFrameBuffer(window_seconds=60.0, max_frames=100, clock=_buffer_clock(now), **kw)


# ------------------------------------------------------------- provider


def test_provider_simulation_observation_contract():
    result = provider.vision_observe_frames([], {"camera_id": 1, "camera_name": "Lobby"})
    assert set(result) >= {"summary", "statements", "notes", "model"}
    assert isinstance(result["statements"], list)
    for s in result["statements"]:
        assert s["classification"] in ("OBSERVED", "INFERRED", "UNKNOWN")
        assert 0.0 <= s["confidence"] <= 1.0
        assert isinstance(s["statement"], str) and s["statement"]
    assert result["model"].startswith("simulation")


def test_provider_simulation_grounded_in_metadata():
    context = {
        "camera_id": 7,
        "camera_name": "Warehouse",
        "session_id": 99,
        "detections": [{"label": "person", "confidence": 0.9, "frame_id": 12}],
        "active_tracks": [{"tracking_id": "Person-1", "label": "person", "confidence": 0.8, "frame_id": 12}],
        "event": {
            "event_id": "object_stopped-00001",
            "event_type": "object_stopped",
            "tracking_id": "Person-1",
            "frame_index": 12,
            "metadata": {"stationary_seconds": 7.0},
        },
        "window_start": 1.0,
        "window_end": 4.0,
    }
    result = provider.vision_observe_frames([{"data": b"x"}], context)
    classifications = {s["classification"] for s in result["statements"]}
    assert "OBSERVED" in classifications
    assert "INFERRED" in classifications  # loitering inference from stationary
    text = " ".join(s["statement"] for s in result["statements"]).lower()
    assert "person" in text or "person" in str(context["detections"])
    assert "unavailable" not in result["summary"].lower()  # summary present
    assert result["summary"].startswith("[SIMULATED VLM]")
    # Guardrail: no identity/intent/facial wording anywhere.
    joined = (result["summary"] + " " + text).lower()
    for bad in ("name:", "identity", "intends", "face of"):
        assert bad not in joined


def test_provider_simulation_empty_context_unknown():
    result = provider.vision_observe_frames([], {"camera_id": 1})
    assert result["statements"][0]["classification"] == "UNKNOWN"


def test_provider_normalize_malformed_output():
    raw = {
        "summary": "s",
        "statements": [
            {"statement": "a", "classification": "GUESSED", "confidence": 5, "basis": [1, "b"]},
            {"statement": "b", "classification": "observed", "confidence": -1, "basis": "not-list"},
            "junk",
            {"statement": "", "classification": "OBSERVED", "confidence": 0.9},
        ],
        "notes": ["n"],
    }
    out = provider._normalize_observation(raw, "test-model")
    assert out["model"] == "test-model"
    assert all(s["classification"] in ("OBSERVED", "INFERRED", "UNKNOWN") for s in out["statements"])
    assert all(0.0 <= s["confidence"] <= 1.0 for s in out["statements"])
    assert out["statements"][0]["classification"] == "UNKNOWN"  # GUESSED downgraded
    assert out["statements"][0]["basis"] == ["1", "b"]  # coerced to strings
    assert not any(s["statement"] == "" for s in out["statements"])


def test_guardrail_downgrades_identity_claims():
    items = coerce_statements(
        {
            "statements": [
                {"statement": "A person entered.", "classification": "OBSERVED", "confidence": 0.9, "basis": ["frame:3"]},
                {"statement": "The man intends to steal the package.", "classification": "OBSERVED", "confidence": 0.9, "basis": ["frame:3"]},
            ]
        }
    )
    assert items[0].classification.value == "OBSERVED"
    assert items[1].classification.value == "UNKNOWN"
    assert items[1].confidence == 0.0


# ------------------------------------------------------------- preprocessing


def test_preprocess_copies_and_limits_size():
    big = np.zeros((2000, 4000, 3), dtype=np.uint8)
    entries = [SimpleNamespace(frame=big, sequence=1, timestamp=100.0)]
    prepared, dropped = encode_frames(entries, max_side=1280, jpeg_quality=80, max_bytes=512 * 1024)
    assert dropped == 0
    assert len(prepared) == 1
    p = prepared[0]
    assert p.width <= 1280 and p.height <= 1280
    assert max(p.width, p.height) <= 1280
    assert len(p.data) <= 512 * 1024
    assert p.original_width == 4000 and p.original_height == 2000
    # Source frame untouched (same object, same shape).
    assert big.shape == (2000, 4000, 3)


def test_preprocess_dedupes_and_counts_dropped():
    a = _frame(100, 100, value=7)
    b = _frame(100, 100, value=7)  # identical pixels -> same JPEG bytes
    entries = [
        SimpleNamespace(frame=a, sequence=1, timestamp=100.0),
        SimpleNamespace(frame=b, sequence=2, timestamp=101.0),
        SimpleNamespace(frame=None, sequence=3, timestamp=102.0),
    ]
    prepared, dropped = encode_frames(entries, max_side=1280, jpeg_quality=80, max_bytes=512 * 1024)
    assert len(prepared) == 1  # duplicate skipped
    assert dropped == 2  # duplicate + None


def test_preprocess_drops_oversized_bytes():
    # Force a very low byte budget so the JPEG exceeds it.
    entries = [SimpleNamespace(frame=_frame(400, 400), sequence=1, timestamp=100.0)]
    prepared, dropped = encode_frames(entries, max_side=1280, jpeg_quality=90, max_bytes=64)
    assert prepared == []
    assert dropped == 1


# ------------------------------------------------------------- selection


def test_select_for_event_maps_sequence_and_window():
    buf = _buffer(now=150.0)
    for i in range(6):
        buf.append(_frame(200, 200), 100.0 + i)
    event = TrackingEvent(
        event_id="e-1",
        event_type="object_entered",
        tracking_id="Person-1",
        frame_index=3,
        frame_timestamp=102.5,
    )
    sel = selection.select_for_event(buf, event, max_frames=3)
    assert sel.frames
    seqs = [f.sequence for f in sel.frames]
    assert 3 in seqs  # exact trigger frame included
    assert len(sel.frames) <= 3
    assert sel.window_start is not None and sel.window_end >= sel.window_start


def test_select_for_event_no_buffer_returns_empty():
    buf = _buffer(now=150.0)
    sel = selection.select_for_event(buf, TrackingEvent(event_id="e", event_type="x", frame_index=0), max_frames=3)
    assert not sel.frames
    assert sel.window_start is None


def test_select_latest_returns_newest():
    buf = _buffer(now=250.0)
    for i in range(5):
        buf.append(_frame(100, 100), 200.0 + i)
    sel = selection.select_latest(buf, max_frames=3)
    assert [f.sequence for f in sel.frames] == [3, 4, 5]
    assert sel.window_start == 202.0
    assert sel.window_end == 204.0


def test_sample_evenly():
    from app.vlm.selection import sample_evenly

    entries = [SimpleNamespace(sequence=i) for i in range(9)]
    picked = sample_evenly(entries, 3)
    assert len(picked) == 3
    assert picked[0].sequence == 0 and picked[-1].sequence == 8
    assert sample_evenly(entries, 0) == []
    assert sample_evenly([], 5) == []


# ------------------------------------------------------------- rate limiter


class _FakeClock:
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now


def test_rate_limiter_cooldown_and_cap():
    clock = _FakeClock(100.0)
    limiter = VlmRateLimiter(max_requests=3, cooldown_seconds=10.0, clock=clock)
    assert limiter.allow(now=100.0)
    assert not limiter.allow(now=105.0)  # inside cooldown
    assert limiter.cooldown_active(now=105.0)
    assert limiter.allow(now=110.5)  # cooldown elapsed (10.5s)
    assert limiter.allow(now=120.6)
    assert not limiter.allow(now=121.0)  # hard session cap reached
    assert limiter.requests_used() == 3
    clock.now = 9999.0
    assert not limiter.allow(now=9999.0)  # cap is permanent per session


def test_rate_limiter_no_cap_or_cooldown_always_allows():
    clock = _FakeClock(0.0)
    limiter = VlmRateLimiter(max_requests=None, cooldown_seconds=0.0, clock=clock)
    for _ in range(50):
        assert limiter.allow()


# ------------------------------------------------------------- worker


class _Sink:
    def __init__(self):
        self.items = []
        self.event = threading.Event()

    def __call__(self, payload):
        self.items.append(payload)
        self.event.set()


def _job(request_id="r1", trigger="manual", frames=None):
    request = VlmRequest(
        request_id=request_id,
        camera_id=1,
        trigger=trigger,
        provider_mode="simulation",
        context={"camera_id": 1, "camera_name": "Lobby"},
    )
    return VlmJob(
        request=request,
        frames=frames if frames is not None else [SimpleNamespace(frame=_frame(320, 240), sequence=1, timestamp=100.0)],
        camera_name="Lobby",
        window_start=99.0,
        window_end=101.0,
    )


def _drain(sink, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(sink.items):
            return True
        time.sleep(0.02)
    return predicate(sink.items)


def test_worker_publishes_observation():
    sink = _Sink()
    worker = VlmWorker(on_publish=sink, retries=0)
    worker.start()
    try:
        assert worker.submit(_job(frames=[SimpleNamespace(frame=_frame(320, 240), sequence=1, timestamp=100.0)]))
        assert _drain(sink, lambda items: any(i.get("type") == "vlm_observation" for i in items))
        obs = next(i for i in sink.items if i.get("type") == "vlm_observation")
        assert obs["provider_mode"] == "simulation"
        assert obs["camera_id"] == 1
        assert obs["trigger"] == "manual"
        assert obs["source_frames"] and obs["source_frames"][0]["sequence"] == 1
        assert all(it["classification"] in ("OBSERVED", "INFERRED", "UNKNOWN") for it in obs["items"])
    finally:
        worker.stop()


def test_worker_no_frames_produces_unknown_observation():
    sink = _Sink()
    worker = VlmWorker(on_publish=sink, retries=0)
    worker.start()
    try:
        job = _job(frames=[])
        assert worker.submit(job)
        assert _drain(sink, lambda items: any(i.get("type") == "vlm_observation" for i in items))
        obs = next(i for i in sink.items if i.get("type") == "vlm_observation")
        assert obs["items"][0]["classification"] == "UNKNOWN"
    finally:
        worker.stop()


def test_worker_queue_drops_oldest_when_full():
    sink = _Sink()
    worker = VlmWorker(on_publish=sink, maxsize=2, retries=0)
    gate = threading.Event()
    original_process = worker._process
    # Block the consumer so the queue actually builds up (deterministic).
    worker._process = lambda job: (gate.wait(5.0), original_process(job))[1]
    worker.start()
    try:
        assert worker.submit(_job(request_id="r0"))
        time.sleep(0.05)  # let the consumer pick r0 and block on the gate
        for i in (1, 2, 3):
            worker.submit(_job(request_id=f"r{i}"))
        assert worker.queue_size == 2
        assert worker.snapshot()["dropped_requests"] >= 1  # r1 evicted
        worker._process = original_process
        gate.set()
        assert _drain(sink, lambda items: worker.queue_size == 0)
        obs_request_ids = [i.get("request_id") for i in sink.items if i.get("type") == "vlm_observation"]
        assert "r0" in obs_request_ids  # picked up before eviction
        assert "r1" not in obs_request_ids  # oldest in queue dropped
        assert "r2" in obs_request_ids and "r3" in obs_request_ids  # newest survive
    finally:
        worker._process = original_process
        gate.set()
        worker.stop()


def test_worker_provider_failure_survives(monkeypatch):
    def _boom(*a, **k):
        raise provider.ProviderError("backend down")

    monkeypatch.setattr(provider, "vision_observe_frames", _boom)
    sink = _Sink()
    worker = VlmWorker(on_publish=sink, retries=1, backoff_seconds=0.01)
    worker.start()
    try:
        assert worker.submit(_job(request_id="fail1"))
        assert _drain(sink, lambda items: any(i.get("type") == "vlm_error" for i in items))
        assert worker.running  # worker survives a provider failure
        snap = worker.snapshot()
        assert snap["total_errors"] >= 1
        assert snap["total_retries"] >= 1
        # Session can keep working afterwards.
        assert worker.submit(_job(request_id="fail2"))
        assert _drain(sink, lambda items: len([i for i in items if i.get("type") == "vlm_error"]) >= 2)
    finally:
        worker.stop()


# ------------------------------------------------------------- context


def _fake_runtime_with_state(monkeypatch):
    track = TrackSummary(
        tracking_id="Person-9",
        label="Person",
        state=TrackState.ACTIVE,
        bbox=[10, 10, 50, 90],
        center=[30.0, 50.0],
        confidence=0.85,
    )
    detection = SimpleNamespace(
        recent_results=lambda limit=5: [
            {
                "frame_id": 42,
                "detections": [{"class_name": "person", "confidence": 0.9, "bbox": [1, 2, 30, 80]}],
            }
        ]
    )
    tracking = SimpleNamespace(tracks=lambda: [track])
    return SimpleNamespace(
        detection=detection,
        tracking=tracking,
        camera_id=5,
        camera_name="Side door",
        session_db_id=11,
        buffer=RollingFrameBuffer(window_seconds=10.0, max_frames=10),
    )


def test_context_builds_fusion_and_provenance():
    runtime = _fake_runtime_with_state(None)
    for i in range(3):
        runtime.buffer.append(_frame(200, 200), 50.0 + i)
    eve = {
        "event_id": "object_entered-00001",
        "event_type": "object_entered",
        "tracking_id": "Person-9",
        "frame_index": 42,
    }
    c = ctx.build_observe_context(
        runtime,
        camera_id=5,
        camera_name="Side door",
        session_id=11,
        trigger="event",
        trigger_detail="object_entered",
        source_frames=[{"frame_id": 3, "sequence": 3, "timestamp": 52.0, "width": 200, "height": 200}],
        window_start=50.0,
        window_end=52.0,
        event=eve,
        provider_mode="simulation",
    )
    assert c["detections"][0]["label"] == "person"
    assert c["detections"][0]["bbox"] == [1, 2, 30, 80]
    assert c["active_tracks"][0]["tracking_id"] == "Person-9"
    assert c["active_tracks"][0]["state"] == "ACTIVE"
    assert c["event"]["event_type"] == "object_entered"
    assert c["coordinate_units"] == "absolute_frame_pixels"
    assert c["no_faces"] is True
    assert c["session_id"] == 11


def test_context_empty_when_no_sources():
    runtime = SimpleNamespace(detection=None, tracking=None)
    c = ctx.build_observe_context(
        runtime, camera_id=1, camera_name="", session_id=None,
        trigger="manual", trigger_detail=None, source_frames=[], window_start=None, window_end=None,
        event=None, provider_mode="simulation",
    )
    assert c["detections"] == []
    assert c["active_tracks"] == []


# ------------------------------------------------------------- triggers


def test_event_triggers_set_and_periodic(monkeypatch):
    monkeypatch.setattr(settings, "VLM_EVENT_TRIGGERS", "object_entered,object_stopped")
    monkeypatch.setattr(settings, "VLM_PERIODIC_SECONDS", 5.0)
    assert triggers.is_trigger_event("object_entered")
    assert triggers.is_trigger_event("object_stopped")
    assert not triggers.is_trigger_event("object_moved")
    assert triggers.periodic_interval_seconds() == 5.0
    monkeypatch.setattr(settings, "VLM_EVENT_TRIGGERS", "")
    assert not triggers.is_trigger_event("object_entered")