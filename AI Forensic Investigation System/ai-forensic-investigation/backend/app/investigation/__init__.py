"""Phase 6 - Forensic retrieval over live evidence.

Deterministic (no LLM) query parsing, hybrid retrieval (Qdrant semantic +
PostgreSQL metadata + temporal + track/event), explainable reranking and
grounded answers that never fabricate identity / intent / timestamps.
"""

from app.investigation.query_parser import ParsedQuery, parse_query
from app.investigation.retrieval import retrieve_investigation_evidence
from app.investigation.rerank import rerank_candidates
from app.investigation.answers import build_answer

__all__ = [
    "ParsedQuery",
    "parse_query",
    "retrieve_investigation_evidence",
    "rerank_candidates",
    "build_answer",
]