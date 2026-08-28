from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


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

    # ---- Part 3: Agentic investigation / evidence verification --------

    # Bounded investigation agent guardrails.
    AGENT_MAX_TOOL_CALLS: int = 12
    AGENT_MAX_STEPS: int = 16
    AGENT_TOOL_TIMEOUT_SECONDS: float = 30.0
    AGENT_RETRY_LIMIT: int = 2

    # Verification thresholds.
    VERIFICATION_SUPPORT_THRESHOLD: float = 0.5
    VERIFICATION_TIMESTAMP_TOLERANCE_SECONDS: float = 2.0
    VERIFICATION_MAX_TIMELINE_EVENTS: int = 100

    # ---- Part 4: Human review + report generation -------------------------

    # Report generation / PDF renderer. "reportlab" renders a real PDF; if the
    # package is not installed the service falls back to plain markdown.
    REPORT_RENDERER: str = "reportlab"
    REPORT_MAX_SECTIONS: int = 11

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
