"""Part 2 - Pydantic schemas for multimodal AI / Video RAG / Policy RAG."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class EvidenceCard(BaseModel):
    evidence_id: str
    video_id: Optional[int] = None
    clip_id: Optional[int] = None
    clip_public_id: Optional[str] = None
    camera_id: Optional[int] = None
    camera_name: Optional[str] = None
    timestamp: float = 0.0
    start_time: float = 0.0
    end_time: Optional[float] = None
    description: str = ""
    objects: List[str] = []
    tracking_ids: List[str] = []
    transcript: str = ""
    detection_confidence: Optional[float] = None
    retrieval_score: float = 0.0
    source_path: str = ""
    verification: Optional[dict] = None


class Analysis(BaseModel):
    entities: List[str] = []
    events: List[str] = []
    temporal: dict = {}
    raw: str = ""


class RAGQueryRequest(BaseModel):
    query: str
    video_id: Optional[int] = None
    camera_id: Optional[int] = None


class RAGQueryResponse(BaseModel):
    query: str
    analysis: Analysis
    status: str
    answer: str
    evidence: List[EvidenceCard] = []


class PolicyOut(BaseModel):
    policy_id: str
    document_name: str
    filename: Optional[str] = None
    source_format: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    chunk_count: int = 0


class PolicyChunkOut(BaseModel):
    id: int
    section: Optional[str] = None
    page: Optional[int] = None
    chunk_index: Optional[int] = None
    text: str


class PolicySearchHit(BaseModel):
    score: float
    policy_id: Optional[int] = None
    document_name: Optional[str] = None
    section: Optional[str] = None
    page: Optional[int] = None
    chunk_index: Optional[int] = None
    text: str


class PolicyQuestionRequest(BaseModel):
    question: str
    video_id: Optional[int] = None


class PolicyQuestionResponse(BaseModel):
    question: str
    status: str
    description: str
    policy_sections: List[PolicySearchHit] = []
    evidence: List[EvidenceCard] = []
    video_id: Optional[int] = None
    clip_id: Optional[int] = None
    policy_id: Optional[int] = None


class FindingOut(BaseModel):
    id: int
    video_id: Optional[int] = None
    clip_id: Optional[int] = None
    finding_status: str
    finding_type: Optional[str] = None
    question: Optional[str] = None
    description: Optional[str] = None
    confidence: Optional[float] = None
    retrieval_score: Optional[float] = None
    policy_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
