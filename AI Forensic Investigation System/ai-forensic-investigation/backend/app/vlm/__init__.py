"""Phase 4 - Real-time live VLM observation layer.

Builds on the Phase 1-3 pipeline (ingest -> sampling -> YOLO -> tracking ->
events) and the existing ``app/ai/provider`` abstraction. The VLM never
replaces detection/tracking/event detection: it authenticates and describes
what is observably visible in evidence frames, grounded as OBSERVED /
INFERRED / UNKNOWN, with full provenance.

The public entry point wired into :class:`app.live.manager.LiveSessionRuntime`
is :class:`app.vlm.session.VlmSession`.
"""