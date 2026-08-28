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
