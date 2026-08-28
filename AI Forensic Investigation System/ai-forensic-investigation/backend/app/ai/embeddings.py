"""Embeddings service.

Modes (in priority order for real usage):

1. ``simulation`` (default when no provider is configured) - deterministic,
   hash-based fixed-dimension embeddings. Identical text always yields identical
   vectors so offline tests are reproducible.

2. OpenAI-compatible ``/embeddings`` endpoint (BGE/E5 served by Ollama, TEI, ...)
   when ``LLM_PROVIDER`` is a live endpoint.

3. Local ``sentence-transformers`` (BGE/E5) if installed - a no-code fallback for
   self-hosted model files.

All modes return normalized vectors of dimension ``QDRANT_VECTOR_SIZE``.
"""

from __future__ import annotations

import hashlib
import logging
import math

from app.core.config import settings

logger = logging.getLogger(__name__)


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _simulate_embed(text: str, dim: int) -> list[float]:
    """Deterministic bag-of-ngrams hash embedding (dimension = settings size)."""
    vec = [0.0] * dim
    tokens = _tokenize(text.lower())
    for token in tokens:
        idx = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % dim
        vec[idx] += 1.0
    # Add a couple of global hashed offsets per token for a little more signal.
    for i in range(min(3, len(tokens))):
        h = int(hashlib.sha256(tokens[i].encode("utf-8")).hexdigest(), 16)
        vec[h % dim] += 0.25
    return _normalize(vec)


def _tokenize(text: str) -> list[str]:
    words = "".join(c if c.isalnum() or c.isspace() else " " for c in text).split()
    tokens = list(words)
    # bigrams give some phrase signal
    tokens += [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
    return tokens


class EmbeddingService:
    def __init__(self) -> None:
        self._model = None
        self._dim = settings.QDRANT_VECTOR_SIZE

    # -- capability ------------------------------------------------------
    @property
    def managing(self) -> str:
        return "simulation"

    def is_simulation(self) -> bool:
        from app.ai.provider import _is_simulation, available as provider_available

        if (settings.LLM_PROVIDER or "").strip().lower() == "simulation":
            return True
        if not settings.LLM_BASE_URL.strip():
            return True
        return not provider_available() and self._local_model() is None

    def _local_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
                self._dim = self._model.get_sentence_embedding_dimension()
            except Exception:  # noqa: BLE001
                self._model = False
        return self._model or None

    # -- embed -----------------------------------------------------------
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.is_simulation():
            return [_simulate_embed(t, self._dim) for t in texts]
        # 1) provider endpoint
        try:
            return self._embed_via_provider(texts)
        except Exception as exc:  # noqa: BLE001
            logger.info("Provider embedding failed (%s); trying local model", exc)
        # 2) local sentence-transformers
        model = self._local_model()
        if model is not None:
            try:
                vecs = model.encode(texts, normalize_embeddings=True).tolist()
                return [v[: self._dim] if len(v) > self._dim else v for v in vecs]
            except Exception as exc:  # noqa: BLE001
                logger.warning("Local embedding failed (%s); falling back to simulation", exc)
        # 3) deterministic fallback
        return [_simulate_embed(t, self._dim) for t in texts]

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_dim(self) -> int:
        return self._dim

    def _embed_via_provider(self, texts: list[str]) -> list[list[float]]:
        import httpx

        url = (settings.LLM_BASE_URL.rstrip("/")) + "/embeddings"
        headers = {"Content-Type": "application/json"}
        if settings.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
        payload = {"model": settings.EMBEDDING_MODEL, "input": texts}
        resp = httpx.post(url, json=payload, headers=headers, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
        embeddings = [item["embedding"] for item in data["data"]]
        dim = len(embeddings[0]) if embeddings else self._dim
        if dim != self._dim:
            # keep configured dim for Qdrant consistency; pad or truncate
            embeddings = [
                (v + ([0.0] * (self._dim - len(v))))[: self._dim] for v in embeddings
            ]
            return [_normalize(v) for v in embeddings]
        return embeddings


embeddings = EmbeddingService()
