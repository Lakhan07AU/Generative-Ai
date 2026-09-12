"""Pluggable LLM/VLM provider layer.

Supports two modes:

* ``openai``  - any OpenAI-compatible chat/completions endpoint (OpenAI, Ollama,
  LM Studio, vLLM, ...) configured via ``LLM_BASE_URL`` / ``LLM_API_KEY`` and the
  ``LLM_MODEL`` / ``VISION_MODEL`` settings.

* ``simulation`` (default) - a deterministic, clearly-labelled offline fallback
  used when no real provider is configured. It still produces structured output
  and valid JSON, but the text is derived programmatically from the observable
  detection/metadata already in the system - it does not fabricate evidence and
  never invents identities or intent.

The rest of the system never knows (or cares) which mode is active: it always
receives the same JSON structure.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

SIMULATION_PROVIDER = "simulation"

# How many keyframes we send to the vision model per clip at most.
MAX_VISION_FRAMES = 3


class ProviderError(RuntimeError):
    """Raised when a real provider fails and we cannot fall back safely."""


def _is_simulation() -> bool:
    return (settings.LLM_PROVIDER or "").strip().lower() == SIMULATION_PROVIDER


def available() -> bool:
    """Whether a live provider is configured (vs. simulation mode)."""
    return not _is_simulation() and bool(settings.LLM_BASE_URL.strip())


# ---------------------------------------------------------------------------
# OpenAI-compatible HTTP helpers
# ---------------------------------------------------------------------------

def _chat_completion(messages: list[dict], model: str, temperature: float = 0.0, max_tokens: int = 1024) -> str:
    url = (settings.LLM_BASE_URL.rstrip("/")) + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=120.0)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(f"chat completion failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Text generation (grounding answers / summaries)
# ---------------------------------------------------------------------------

def generate_text(prompt: str, system: Optional[str] = None) -> str:
    """Generate free text. In simulation mode returns a deterministic stub."""
    if _is_simulation() or not available():
        return _simulate_text(prompt)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        return _chat_completion(messages, settings.LLM_MODEL)
    except ProviderError as exc:
        logger.warning("Provider unavailable (%s); falling back to simulation", exc)
        return _simulate_text(prompt)


def _simulate_text(prompt: str) -> str:
    """Deterministic placeholder for text generation.

    Clearly labelled as a simulation output so it is never mistaken for a real
    model result.
    """
    snippet = prompt.strip()[:140].replace("\n", " ")
    return (
        "[SIMULATED - no LLM configured] "
        "This is a deterministic simulation response. "
        f"Prompt: {snippet}"
    )


# ---------------------------------------------------------------------------
# Vision (VLM) structured clip description
# ---------------------------------------------------------------------------

def vision_describe_clip(
    image_paths: list[str],
    clip_context: dict[str, Any],
) -> dict[str, Any]:
    """Return a structured semantic description of a clip from its keyframes.

    ``clip_context`` is observable data already known about the clip (start/end,
    detections, tracking ids, transcript reference). The model describes only what
    is observable - it must not infer human intent.
    """
    if not _is_simulation() and available():
        return _real_vision_describe(image_paths, clip_context)
    return _simulate_vision_describe(clip_context)


def _real_vision_describe(image_paths: list[str], clip_context: dict[str, Any]) -> dict[str, Any]:
    import base64

    if not image_paths:
        return _simulate_vision_describe(clip_context)

    def _b64(path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    images_payload = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_b64(p)}"}}
        for p in image_paths[:MAX_VISION_FRAMES]
    ]
    user_content = [
        {
            "type": "text",
            "text": (
                "You are a forensic video analyst. Describe ONLY observable evidence "
                "in these keyframes from a CCTV clip. Never infer human intent, "
                "identity, or names. Return strict JSON with keys: "
                "summary (string), objects (array of strings), "
                "observable_actions (array of strings), location_context (string), "
                f"transcript_reference (string). Clip metadata: {json.dumps(clip_context)}"
            ),
        },
        *images_payload,
    ]
    messages = [{"role": "user", "content": user_content}]
    try:
        raw = _chat_completion(messages, settings.VISION_MODEL, max_tokens=700)
        return _parse_json_object(raw) or _simulate_vision_describe(clip_context)
    except ProviderError as exc:
        logger.warning("VLM unavailable (%s); using simulation description", exc)
        return _simulate_vision_describe(clip_context)


def _simulate_vision_describe(clip_context: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, evidence-derived description.

    Uses the actual detections for the clip so output is grounded in observable
    data (or honestly empty when there are none). Clearly labelled simulation.
    """
    detections = clip_context.get("detections", [])
    labels = {}
    tracking = set()
    for d in detections:
        lbl = d.get("label")
        if not lbl:
            continue
        labels[lbl] = labels.get(lbl, 0) + 1
        if d.get("tracking_id"):
            tracking.add(d["tracking_id"])

    objects = [f"{lbl} (x{count})" for lbl, count in sorted(labels.items())] or []
    actions = []
    for tid in sorted(tracking):
        actions.append(f"{tid} moves across the monitored area")
    location = clip_context.get("location_context") or "monitored area"
    if not actions:
        actions = ["no person or object movement recorded"]

    summary = (
        "[SIMULATED VLM] "
        f"From {clip_context.get('start_time', 0)}s to {clip_context.get('end_time', 0)}s, "
        f"{len(objects)} object type(s) observed in the {location}."
    )
    return {
        "summary": summary,
        "objects": objects,
        "observable_actions": actions,
        "location_context": location,
        "transcript_reference": clip_context.get("transcript_reference", ""),
    }


# ---------------------------------------------------------------------------
# Live frame observation (Phase 4)
# ---------------------------------------------------------------------------

P3_OBSERVATION_CLASSES = ("OBSERVED", "INFERRED", "UNKNOWN")

MAX_OBSERVATION_STATEMENTS = 32


def _resolve_mode(provider_override: Optional[str] = None) -> str:
    """Resolve the active provider mode, allowing per-call override."""
    mode = (provider_override or settings.LLM_PROVIDER or "").strip().lower()
    if mode == SIMULATION_PROVIDER:
        return SIMULATION_PROVIDER
    if mode:
        return mode
    return SIMULATION_PROVIDER


def vision_observe_frames(
    prepared_frames: list[dict],
    observe_context: dict[str, Any],
    provider_override: Optional[str] = None,
) -> dict[str, Any]:
    """Return a grounded structured observation of live frames.

    ``prepared_frames`` is a list of preprocessed JPEG frames with keys ``data``
    (JPEG bytes) plus passive metadata (``frame_id``, ``sequence``,
    ``timestamp``, ``width``, ``height``). ``observe_context`` carries ONLY
    observable metadata already known to the system (camera/session ids, source
    frame refs, detections, active tracks, events, window bounds).

    Contract of the returned dict (later normalised against the Phase 4
    schema):
        {"summary": str,
         "statements": [{"statement", "classification", "confidence", "basis"}],
         "notes": [str],
         "model": str}

    ``classification`` is one of OBSERVED / INFERRED / UNKNOWN. The model is
    told never to infer human intent, identity, or names, and never to invent
    timestamps or metadata. In simulation mode output is derived deterministically
    from the supplied metadata and is clearly labelled.
    """
    mode = _resolve_mode(provider_override)
    if mode != SIMULATION_PROVIDER and available():
        return _real_observe_frames(prepared_frames, observe_context, provider_override)
    return _simulate_observe_frames(observe_context, provider_override)


def _real_observe_frames(
    prepared_frames: list[dict],
    observe_context: dict[str, Any],
    provider_override: Optional[str] = None,
) -> dict[str, Any]:
    import base64

    if not prepared_frames:
        return _simulate_observe_frames(observe_context, provider_override)

    images_payload = []
    for frame in prepared_frames[:MAX_VISION_FRAMES]:
        data = frame.get("data")
        if not data:
            continue
        b64 = base64.b64encode(data).decode("utf-8")
        images_payload.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
        )
    if not images_payload:
        return _simulate_observe_frames(observe_context, provider_override)

    user_content = [
        {
            "type": "text",
            "text": (
                "You are a forensic video analyst examining LIVE camera frames. "
                "Describe ONLY observable evidence. Classify every statement as "
                "OBSERVED (directly visible in the frames or given metadata), "
                "INFERRED (reasoned from the given metadata, clearly labelled), or "
                "UNKNOWN (not determinable). "
                "NEVER infer human intent, names, identity, or perform facial or "
                "biometric identification. NEVER invent timestamps, IDs, or metadata "
                "not provided. "
                f"Known metadata (only observable facts): {json.dumps(observe_context)} "
                "Return STRICT JSON with keys: summary (string), statements (array of "
                "{statement: string, classification: 'OBSERVED'|'INFERRED'|'UNKNOWN', "
                "confidence: number 0-1, basis: array of source ref strings}), "
                "notes (array of strings)."
            ),
        },
        *images_payload,
    ]
    messages = [{"role": "user", "content": user_content}]
    try:
        raw = _chat_completion(
            messages,
            settings.VISION_MODEL,
            temperature=0.0,
            max_tokens=1000,
        )
        parsed = _parse_json_object(raw)
        if parsed is not None:
            return _normalize_observation(parsed, settings.VISION_MODEL)
        return _simulate_observe_frames(observe_context, provider_override)
    except ProviderError as exc:
        logger.warning("VLM observation unavailable (%s); using simulation", exc)
        return _simulate_observe_frames(observe_context, provider_override)


def _normalize_observation(parsed: dict, model: str) -> dict[str, Any]:
    """Coerce raw VLM JSON into the observation contract with guardrails."""
    statements = []
    for item in (parsed.get("statements") or [])[:MAX_OBSERVATION_STATEMENTS]:
        if not isinstance(item, dict):
            continue
        cls = str(item.get("classification", "")).strip().upper()
        if cls not in P3_OBSERVATION_CLASSES:
            cls = "UNKNOWN"
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        statement = str(item.get("statement", "")).strip()
        if not statement:
            continue
        basis = item.get("basis") or []
        basis = [str(b) for b in basis if isinstance(b, (str, int, float))]
        statements.append(
            {
                "statement": statement,
                "classification": cls,
                "confidence": confidence,
                "basis": basis,
            }
        )
    if not statements:
        statements = [
            {
                "statement": "The model returned no statements; content could not be verified.",
                "classification": "UNKNOWN",
                "confidence": 0.0,
                "basis": [],
            }
        ]
    notes_in = parsed.get("notes") or []
    notes = [str(n) for n in notes_in if isinstance(n, (str, int, float))]
    return {
        "summary": str(parsed.get("summary", "")).strip(),
        "statements": statements,
        "notes": notes,
        "model": model,
    }


def _simulate_observe_frames(
    observe_context: dict[str, Any],
    provider_override: Optional[str] = None,
) -> dict[str, Any]:
    """Deterministic, evidence-derived observation for simulation mode."""
    camera = observe_context.get("camera_id", "?")
    camera_name = observe_context.get("camera_name", "")
    session = observe_context.get("session_id", "")
    frames_ref = observe_context.get("source_frames") or []
    detections = observe_context.get("detections") or []
    tracks = observe_context.get("active_tracks") or []
    event = observe_context.get("event") or {}
    window_start = observe_context.get("window_start")
    window_end = observe_context.get("window_end")

    statements: list[dict] = []
    basis_ctx = [f"camera:{camera}"]
    if session:
        basis_ctx.append(f"session:{session}")

    if detections or tracks or event:
        by_label: dict[str, int] = {}
        for d in detections:
            lbl = d.get("label") or d.get("class_name") or ""
            if lbl:
                by_label[lbl] = by_label.get(lbl, 0) + 1
                frame_ref = d.get("frame_id")
                basis = list(basis_ctx)
                if frame_ref is not None:
                    basis.append(f"frame:{frame_ref}")
                statements.append(
                    {
                        "statement": f"Detected {lbl} at frame {frame_ref} (confidence {float(d.get('confidence', 0.0)):.2f}).",
                        "classification": "OBSERVED",
                        "confidence": max(0.0, min(1.0, float(d.get("confidence", 0.0)))),
                        "basis": basis,
                    }
                )
            break  # only leading detection frame drives the label summary

        for t in tracks:
            tid = t.get("tracking_id")
            lbl = t.get("label") or "object"
            frame_ref = t.get("frame_id")
            basis = list(basis_ctx)
            if tid:
                basis.append(f"track:{tid}")
            if frame_ref is not None:
                basis.append(f"frame:{frame_ref}")
            statements.append(
                {
                    "statement": f"Track {tid} ({lbl}) was active at frame {frame_ref}.",
                    "classification": "OBSERVED",
                    "confidence": max(0.0, min(1.0, float(t.get("confidence", 0.0) or 0.0))) or 0.6,
                    "basis": basis,
                }
            )

        if event:
            etype = event.get("event_type") or ""
            eid = event.get("event_id")
            tid = event.get("tracking_id")
            frame_ref = event.get("frame_index")
            basis = list(basis_ctx)
            if eid:
                basis.append(f"event:{eid}")
            if tid:
                basis.append(f"track:{tid}")
            if frame_ref is not None:
                basis.append(f"frame:{frame_ref}")
            if etype:
                statements.append(
                    {
                        "statement": f"Tracking event '{etype}' recorded for track {tid} at frame {frame_ref}.",
                        "classification": "OBSERVED",
                        "confidence": 0.95,
                        "basis": basis,
                    }
                )
            stationary = event.get("metadata", {}).get("stationary_seconds")
            if etype == "object_stopped" and stationary is not None:
                statements.append(
                    {
                        "statement": f"Track {tid} was stationary for {float(stationary):.1f}s, which may indicate loitering or abandonment.",
                        "classification": "INFERRED",
                        "confidence": 0.55,
                        "basis": basis,
                    }
                )

    if not statements:
        statements = [
            {
                "statement": "No objects were detected in the selected frames; visual content could not be verified.",
                "classification": "UNKNOWN",
                "confidence": 0.0,
                "basis": basis_ctx,
            }
        ]

    n_frames = len(frames_ref)
    window_txt = ""
    if window_start is not None and window_end is not None:
        window_txt = f" in window [{window_start:.1f}s, {window_end:.1f}s]"
    summary = (
        "[SIMULATED VLM] "
        f"Camera {camera}{' (' + camera_name + ')' if camera_name else ''}: "
        f"{n_frames} source frame(s){window_txt}; "
        f"{len(detections)} detection(s), {len(tracks)} active track(s)."
    )
    return {
        "summary": summary,
        "statements": statements,
        "notes": [
            "Simulation provider: deterministic fallback. No real VLM was queried.",
            "Statements are derived from detection/tracking metadata already present in the system.",
        ],
        "model": f"simulation:{provider_override or settings.LLM_PROVIDER or 'default'}",
    }


# ---------------------------------------------------------------------------
# Structured JSON parsing helper (robust against model wrappers)
# ---------------------------------------------------------------------------

def _parse_json_object(raw: str) -> Optional[dict]:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Try to pull the first {...} block out of the text.
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def parse_json_object(raw: str) -> Optional[dict]:
    return _parse_json_object(raw)
