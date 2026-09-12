"""Phase 6 investigation search API contracts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.core.config import settings


class InvestigationSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    case_id: int
    top_k: Optional[int] = Field(default=None, ge=1, le=int(settings.RAG_TOP_K))


class EvidenceCard(BaseModel):
    rank: int
    evidence_id: str
    evidence_type: str
    source: Optional[str] = None
    camera_id: Optional[int] = None
    camera_name: Optional[str] = None
    session_id: Optional[int] = None
    timestamp: Optional[float] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    event_id: Optional[str] = None
    event_type: Optional[str] = None
    tracking_id: Optional[str] = None
    object_class: Optional[str] = None
    vlm_observation_id: Optional[str] = None
    storage_path: Optional[str] = None
    sha256: Optional[str] = None
    content_text: str = ""
    retrieval_score: Optional[float] = None
    reasons: List[str] = Field(default_factory=list)
    verified: bool = False


class InvestigationSearchResponse(BaseModel):
    query: str
    status: str
    answer: str
    confidence: float
    results: List[EvidenceCard] = Field(default_factory=list)
    sources: Dict[str, Any] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)
    analysis: Dict[str, Any] = Field(default_factory=dict)