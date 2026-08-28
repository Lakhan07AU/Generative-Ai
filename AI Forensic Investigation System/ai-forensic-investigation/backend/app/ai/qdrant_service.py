"""Qdrant vector-store service.

Collections:
  * ``video_evidence`` - one point per clip (semantic description + metadata)
  * ``policy_chunks``  - one point per chunked policy section

Metadata stored on evidence points: video_id, camera_id, clip_id, start_time,
end_time, event_type, objects, tracking_ids, transcript, description.

When Qdrant is not reachable (e.g. running unit tests without the Docker
service) the service transparently falls back to an in-memory cosine search
implementation so the RAG logic remains fully testable offline.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class _InMemoryStore:
    """Dead-simple in-memory vector store used when Qdrant is unavailable."""

    def __init__(self) -> None:
        self.points: list[dict] = []

    def upsert(self, point: dict) -> None:
        existing = [p for p in self.points if p["id"] == point["id"]]
        for p in existing:
            self.points.remove(p)
        self.points.append(point)

    def search(self, vector: list[float], limit: int, where: Optional[dict] = None) -> list[dict]:
        scored = []
        for p in self.points:
            if where and not self._match(p, where):
                continue
            score = _cosine(vector, p["vector"])
            scored.append((score, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [self._to_hit(score, p) for score, p in scored[:limit]]

    def _match(self, p: dict, where: dict) -> bool:
        payload = p["payload"]
        for key, cond in where.items():
            if cond.get("$eq") is not None and payload.get(key) != cond["$eq"]:
                return False
            if cond.get("$gte") is not None and (payload.get(key) is None or payload[key] < cond["$gte"]):
                return False
            if cond.get("$lte") is not None and (payload.get(key) is None or payload[key] > cond["$lte"]):
                return False
            if cond.get("$in") is not None and payload.get(key) not in cond["$in"]:
                return False
        return True

    def _to_hit(self, score: float, p: dict) -> dict:
        return {
            "id": p["id"],
            "score": float(score),
            "payload": dict(p["payload"]),
        }

    def count(self, collection: Optional[str] = None) -> int:
        return len(self.points)

    def delete(self, point_id: Any) -> None:
        self.points = [p for p in self.points if p["id"] != point_id]


class QdrantService:
    def __init__(self) -> None:
        self._client = None
        self._backend: Optional[str] = None
        self._mem: dict[str, _InMemoryStore] = {}
        self.sim = settings.QDRANT_VECTOR_SIZE

    # -- connection ------------------------------------------------------
    def _connect(self):
        if self._client is not None or self._backend == "memory":
            return
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qm

            self._client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
            # ping
            self._client.get_collections()
            self._backend = "qdrant"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant unavailable (%s); using in-memory fallback", exc)
            self._client = None
            self._backend = "memory"
            self._mem = {}

    def _backend_name(self) -> str:
        if self._backend is None:
            self._connect()
        return self._backend or "memory"

    def ensure_collections(self) -> None:
        self._connect()
        if self._backend == "qdrant":
            from qdrant_client.http import models as qm

            for name in (settings.QDRANT_COLLECTION_EVIDENCE, settings.QDRANT_COLLECTION_POLICY):
                existing = [c.name for c in self._client.get_collections().collections]
                if name not in existing:
                    self._client.create_collection(
                        collection_name=name,
                        vectors_config=qm.VectorParams(
                            size=settings.QDRANT_VECTOR_SIZE,
                            distance=qm.Distance.COSINE,
                        ),
                    )
        else:
            self._mem.setdefault(settings.QDRANT_COLLECTION_EVIDENCE, _InMemoryStore())
            self._mem.setdefault(settings.QDRANT_COLLECTION_POLICY, _InMemoryStore())

    def _store(self, collection: str) -> _InMemoryStore:
        return self._mem.setdefault(collection, _InMemoryStore())

    # -- indexing --------------------------------------------------------
    def index(self, collection: str, point_id: Any, vector: list[float], payload: dict) -> None:
        self.ensure_collections()
        if self._backend == "qdrant":
            from qdrant_client.http import models as qm

            self._client.upsert(
                collection_name=collection,
                points=[qm.PointStruct(id=str(point_id), vector=vector, payload=payload)],
            )
        else:
            self._store(collection).upsert({"id": str(point_id), "vector": vector, "payload": payload})

    def index_evidence(self, point_id: Any, vector: list[float], payload: dict) -> None:
        self.index(settings.QDRANT_COLLECTION_EVIDENCE, point_id, vector, payload)

    def index_policy(self, point_id: Any, vector: list[float], payload: dict) -> None:
        self.index(settings.QDRANT_COLLECTION_POLICY, point_id, vector, payload)

    # -- search ----------------------------------------------------------
    def search(self, collection: str, vector: list[float], limit: int, where: Optional[dict] = None) -> list[dict]:
        self.ensure_collections()
        if self._backend == "qdrant":
            from qdrant_client.http import models as qm

            qfilter = None
            if where:
                qfilter = qm.Filter(
                    must=[qm.FieldCondition(key=k, match=qm.MatchValue(value=v["$eq"])) for k, v in where.items() if "$eq" in v]
                    + [
                        qm.FieldCondition(key=k, range=qm.Range(gte=v["$gte"], lte=v.get("$lte")))
                        for k, v in where.items() if "$gte" in v or "$lte" in v
                    ]
                    + [
                        qm.FieldCondition(key=k, match=qm.MatchAny(any=v["$in"]))
                        for k, v in where.items() if "$in" in v
                    ]
                )
            hits = self._client.search(
                collection_name=collection,
                query_vector=vector,
                limit=limit,
                query_filter=qfilter,
            )
            return [
                {"id": h.id, "score": float(h.score), "payload": dict(h.payload or {})}
                for h in hits
            ]
        return self._store(collection).search(vector, limit, where)

    def search_evidence(self, vector: list[float], limit: int, where: Optional[dict] = None) -> list[dict]:
        return self.search(settings.QDRANT_COLLECTION_EVIDENCE, vector, limit, where)

    def search_policy(self, vector: list[float], limit: int, where: Optional[dict] = None) -> list[dict]:
        return self.search(settings.QDRANT_COLLECTION_POLICY, vector, limit, where)

    # -- misc ------------------------------------------------------------
    def delete(self, collection: str, point_id: Any) -> None:
        self.ensure_collections()
        if self._backend == "qdrant":
            self._client.delete(
                collection_name=collection,
                points_selector=qm.PointIdsList(points=[str(point_id)]),
            )
        else:
            self._store(collection).delete(point_id)

    def count(self, collection: str) -> int:
        self.ensure_collections()
        if self._backend == "qdrant":
            return self._client.count(collection_name=collection).count
        return self._store(collection).count()


qdrant = QdrantService()
