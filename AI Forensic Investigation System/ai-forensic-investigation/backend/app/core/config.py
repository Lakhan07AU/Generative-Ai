from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Settings(BaseSettings):
    """Application settings loaded from environment / .env."""

    DATABASE_URL: str = "postgresql+psycopg2://forensics:forensics_password@localhost:5432/forensics"

    SECRET_KEY: str = "change_me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120

    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_SECURE: bool = False
    MINIO_BUCKET_VIDEOS: str = "forensics-videos"
    MINIO_BUCKET_CLIPS: str = "forensics-clips"
    MINIO_BUCKET_FRAMES: str = "forensics-frames"
    MINIO_BUCKET_THUMBNAILS: str = "forensics-thumbnails"
    MINIO_BUCKET_POLICIES: str = "forensics-policies"
    MINIO_BUCKET_REPORTS: str = "forensics-reports"

    YOLO_MODEL: str = "yolov8n.pt"
    SCENE_SENSITIVITY: float = 30.0
    MAX_CLIPS: int = 50
    MAX_FRAMES_PER_CLIP: int = 5

    BACKEND_CORS_ORIGINS: str = "http://localhost:3000"

    DATA_DIR: str = "data"

    # ---- Part 2: Multimodal AI / Video RAG / Policy RAG ----

    # Primary LLM/VLM provider. "openai" means any OpenAI-compatible endpoint
    # (OpenAI, Ollama, LM Studio, vLLM, etc). "simulation" is the deterministic
    # offline fallback used when no real provider is configured.
    LLM_PROVIDER: str = "simulation"

    # OpenAI-compatible base URL + key. For a free local provider (e.g. Ollama at
    # http://localhost:11434/v1) the key may be a placeholder like "ollama".
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""

    # Which model to use for text generation / grounding answers.
    LLM_MODEL: str = "gpt-4o-mini"
    # Which model to use for vision (VLM) understanding of keyframes.
    VISION_MODEL: str = "gpt-4o-mini"
    # Which model to use for embeddings (BGE/E5 family are recommended).
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"

    # Transcription model reference (whisper). "simulation" uses deterministic
    # pseudo-segments; otherwise a whisper/faster-whisper model name.
    WHISPER_MODEL: str = "simulation"
    WHISPER_LANGUAGE: str = "en"

    # Qdrant vector store endpoint.
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION_EVIDENCE: str = "video_evidence"
    QDRANT_COLLECTION_POLICY: str = "policy_chunks"
    QDRANT_VECTOR_SIZE: int = 384

    # Video RAG retrieval configuration.
    RAG_TOP_K: int = 8
    RAG_RERANK_KEEP: int = 4
    RAG_VERIFICATION_THRESHOLD: float = 0.55

    # ---- Phase 6: Investigation retrieval bounds ---------------------------
    # Global cap on candidates the reranked context may hold.
    RAG_MAX_CONTEXT_ITEMS: int = 8
    # Cap on evidence records surfaced per distinct event (dedup noise).
    RAG_MAX_EVIDENCE_PER_EVENT: int = 3
    # SSE-style ingestion is unaffected; this bounds memory+latency of answers.

    # ---- Part 3: Agentic investigation / evidence verification --------

    # Bounded investigation agent guardrails.
    AGENT_MAX_TOOL_CALLS: int = 12
    AGENT_MAX_STEPS: int = 16
    AGENT_TOOL_TIMEOUT_SECONDS: float = 30.0
    AGENT_RETRY_LIMIT: int = 2

    # ---- Phase 7: Controlled investigation orchestration ------------------
    # Hard bounds on a single Phase 7 agent run. The graph verifies these caps
    # at every node boundary: a misbehaving node can never exceed them.
    AGENT_MAX_RUN_STEPS: int = 8
    AGENT_MAX_RUN_TOOL_CALLS: int = 14
    AGENT_MAX_RUN_EVIDENCE: int = 40
    AGENT_MAX_RUN_SECONDS: float = 120.0
    # Per-retrieval top_k used by the investigation tools (bounded).
    AGENT_RUN_TOP_K: int = 8
    # When true, a run that produced reviewable findings pauses at READY_FOR_REVIEW
    # until a human approves (APPROVE -> COMPLETED) or rejects (REJECT ->
    # CANCELLED). Runs without reviewable findings auto-complete.
    AGENT_REQUIRE_HUMAN_REVIEW: bool = True
    # Conflict detection window (seconds): evidence of the same track whose
    # timestamps differ by less than this is considered temporally overlapping.
    AGENT_CONFLICT_TOLERANCE_SECONDS: float = 10.0

    # Verification thresholds.
    VERIFICATION_SUPPORT_THRESHOLD: float = 0.5
    VERIFICATION_TIMESTAMP_TOLERANCE_SECONDS: float = 2.0
    VERIFICATION_MAX_TIMELINE_EVENTS: int = 100

    # ---- Phase 8: Forensic verification / timeline reconstruction ---------
    # Deterministic, evidence-grounded forensic analysis layered on top of a
    # Phase 7 run: correlation, timeline reconstruction, finding verification,
    # contradiction/gap detection, multi-camera correlation and reporting.
    FORENSIC_MAX_TIMELINE_ENTRIES: int = 200
    # Entries whose event times fall within this window are merged into one
    # composite timeline entry (same track + event type).
    FORENSIC_OVERLAP_EPSILON_SECONDS: float = 2.0
    # Largest event-time gap considered "continuous coverage" before a
    # missing-time-range gap is reported.
    FORENSIC_GAP_THRESHOLD_SECONDS: float = 30.0
    # Below this event-time gap two entries are reported as NEAR.
    FORENSIC_NEAR_SECONDS: float = 5.0
    # Evidence whose larger dimension is below this many pixels is marked
    # LOW_RESOLUTION and cannot produce an OBSERVED classification alone.
    FORENSIC_LOW_RESOLUTION_PX: int = 480
    # max(width, height) of an evidence frame below this is marked low res.
    FORENSIC_REPORT_RENDERER: str = "reportlab"
    FORENSIC_REPORT_TITLE_PREFIX: str = "Investigation Report"

    # ---- Part 4: Human review + report generation -------------------------

    # Report generation / PDF renderer. "reportlab" renders a real PDF; if the
    # package is not installed the service falls back to plain markdown.
    REPORT_RENDERER: str = "reportlab"
    REPORT_MAX_SECTIONS: int = 11

    # ---- Phase 1: Real-time mobile camera (WebRTC ingest) ------------------

    # Target sampling rate for live frames entering the rolling buffer.
    LIVE_SESSION_FPS: float = 5.0
    # Rolling buffer keeps the most recent N seconds of sampled footage.
    LIVE_BUFFER_WINDOW_SECONDS: float = 15.0
    # Rolling buffer frame budget (hard cap on buffered sampled frames).
    LIVE_BUFFER_MAX_FRAMES: int = 150
    # Hard cap on accepted source frames/sec before time-based sampling.
    LIVE_SOURCE_FPS_CAP: float = 30.0
    # Larger raw frames (bytes) are rejected by ingestion to bound memory.
    LIVE_MAX_FRAME_BYTES: int = 4 * 1024 * 1024
    # ICE servers (STUN/TURN) used by the receive-only WebRTC peer. JSON list of
    # RTCIceServer objects with "urls" (and optional "username"/"credential"),
    # e.g. [{"urls": ["stun:stun.l.google.com:19302"]}]. Empty by default:
    # host-candidate-only is enough for the same-LAN physical demo. Set this when
    # the phone and backend are separated by NAT.
    WEBRTC_ICE_SERVERS: str = "[]"

    # ---- Phase 2: Real-time YOLO detection -------------------------------

    # Master switch: when disabled, live sessions run without inference.
    YOLO_DETECTION_ENABLED: bool = True
    # Confidence threshold for detections kept in the result.
    YOLO_CONF_THRESHOLD: float = 0.30
    # IoU threshold used by Ultralytics NMS.
    YOLO_IOU_THRESHOLD: float = 0.45
    # Inference device: "cpu", "cuda", "mps", or "cpu:0" etc.
    YOLO_DEVICE: str = "cpu"
    # Inference input image size (square, pixels).
    YOLO_IMGSZ: int = 640
    # Maximum number of detections returned per frame.
    YOLO_MAX_DETECTIONS: int = 100
    # Bounded per-session inference queue (frames waiting to be processed).
    DETECTION_QUEUE_SIZE: int = 8
    # Bounded history of the most recent detection results kept in memory.
    DETECTION_RECENT_FRAMES: int = 200

    # ---- Phase 3: Real-time multi-object tracking ---------------------------
    TRACKING_ENABLED: bool = True
    TRACKING_IOU_THRESHOLD: float = 0.3
    TRACKING_MAX_MISSING: int = 30
    TRACKING_MAX_TRACKS: int = 200

    # ---- Phase 4: Real-time live VLM observations ----------------------------
    # Master switch for the live VLM observation layer. When disabled sessions
    # run without any VLM requests (status reports vlm_enabled=False).
    VLM_ENABLED: bool = True
    # Provider mode for live observations. Empty means "inherit LLM_PROVIDER".
    # The existing app/ai/provider abstraction decides simulation vs real mode.
    VLM_PROVIDER: str = ""
    # Event types that may trigger an observation. Empty disables event triggers.
    VLM_EVENT_TRIGGERS: str = "object_entered,object_stopped,object_reappeared,prolonged_presence,object_exited"
    # Periodic trigger interval in seconds (0 = disabled).
    VLM_PERIODIC_SECONDS: float = 0.0
    # Bounded per-session queue of pending observation requests.
    VLM_MAX_QUEUE: int = 16
    # Hard cap on observation requests per session.
    VLM_MAX_REQUESTS_PER_SESSION: int = 60
    # Minimum seconds between provider calls per session (cost control).
    VLM_COOLDOWN_SECONDS: float = 30.0
    # Seconds to wait for a queue entry before the worker publishes a keepalive.
    VLM_KEEPALIVE_SECONDS: float = 1.0
    # Max frames sent to the VLM per observation request (evidence selection is
    # supposed to send the MINIMUM visual data, never every buffered frame).
    VLM_MAX_FRAMES_PER_REQUEST: int = 3
    # Preprocessing: copy frames downscaled to at most this many pixels/side.
    VLM_MAX_IMAGE_SIDE: int = 1280
    # JPEG quality for the downscaled evidence frames.
    VLM_JPEG_QUALITY: int = 80
    # Hard cap on encoded evidence frame bytes (frames over this are dropped).
    VLM_MAX_IMAGE_BYTES: int = 512 * 1024
    # Per-session worker concurrency (1 = strictly sequential provider calls).
    VLM_CONCURRENCY: int = 1
    # Transient failure retries per request (with backoff) before giving up.
    VLM_RETRIES: int = 2
    VLM_RETRY_BACKOFF_SECONDS: float = 1.0
    # How many recent observations a session keeps for status/replay.
    VLM_RECENT_OBSERVATIONS: int = 5

    # ---- Phase 5: Live evidence capture + durable indexing -------------------
    # Master switch: when disabled no live evidence is captured from tracking
    # events or VLM observations, and persistence/indexing is skipped.
    EVIDENCE_ENABLED: bool = True
    # Number of buffered frames captured per evidence record (1 = the exact
    # trigger/best frame; the event/observation window is preserved in metadata).
    EVIDENCE_MAX_FRAMES_PER_CAPTURE: int = 1
    # Preprocessing: evidence frames are copy-encoded JPEGs (never the raw
    # buffer) capped to at most this many pixels/side and this byte budget.
    EVIDENCE_MAX_IMAGE_SIDE: int = 1280
    EVIDENCE_JPEG_QUALITY: int = 92
    EVIDENCE_MAX_IMAGE_BYTES: int = 1024 * 1024
    # Bounded global queue of evidence records waiting to be vector-indexed.
    EVIDENCE_INDEX_QUEUE_SIZE: int = 64
    # Index worker retries before an evidence record is marked FAILED.
    EVIDENCE_INDEX_MAX_ATTEMPTS: int = 3
    EVIDENCE_INDEX_RETRY_BACKOFF_SECONDS: float = 1.0
    # Cap on evidence records returned by the listing/search APIs.
    EVIDENCE_LIST_LIMIT: int = 100

    # ---- Demo Investigation Dataset ---------------------------------------------
    # Absolute, backend-anchored: <backend>/data/demo_investigation. Overridable
    # via the DEMO_DATA_DIR environment variable.
    DEMO_DATA_DIR: str = os.path.join(BACKEND_DIR, "data", "demo_investigation")

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.BACKEND_CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
