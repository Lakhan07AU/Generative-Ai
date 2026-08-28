"""Part 3 - Pydantic schemas for agentic investigation / evidence verification."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Claims & evidence traceability
# ---------------------------------------------------------------------------


class ClaimEvidenceCreate(BaseModel):
    clip_id: Optional[int] = None
    frame_id: Optional[int] = None
    timestamp: Optional[float] = None
    evidence_type: Optional[str] = "clip"
    relevance_score: Optional[float] = None


class ClaimCreate(BaseModel):
    investigation_id: int
    claim_text: str
    claim_type: str = "OBSERVATION"
    evidence: List[ClaimEvidenceCreate] = []


class ClaimEvidenceOut(BaseModel):
    id: int
    claim_id: int
    clip_id: Optional[int] = None
    frame_id: Optional[int] = None
    timestamp: Optional[float] = None
    evidence_type: Optional[str] = None
    relevance_score: Optional[float] = None

    model_config = {"from_attributes": True}


class VerificationOut(BaseModel):
    id: int
    claim_id: int
    checks: Optional[dict] = None
    result: str
    reason: Optional[str] = None
    verifier_version: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_validator("checks", mode="before")
    @classmethod
    def _parse_checks(cls, v):
        if isinstance(v, str):
            import json

            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return v


class ClaimOut(BaseModel):
    id: int
    investigation_id: int
    claim_text: str
    claim_type: str
    status: str
    confidence: Optional[float] = None
    created_at: Optional[datetime] = None
    evidence_links: List[ClaimEvidenceOut] = []
    verifications: List[VerificationOut] = []

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

class TimelineEventOut(BaseModel):
    id: int
    investigation_id: int
    timestamp: float
    description: str
    status: str
    evidence_ids: Optional[List[str]] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Agent chat / investigation workspace
# ---------------------------------------------------------------------------


class InvestigationCreate(BaseModel):
    title: str
    query: str
    description: Optional[str] = None
    video_id: Optional[int] = None


class InvestigationOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    query: str
    video_id: Optional[int] = None
    status: str
    created_by_user_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class InvestigationDetail(InvestigationOut):
    claims: List[ClaimOut] = []
    timeline_events: List[TimelineEventOut] = []


class AgentToolCall(BaseModel):
    name: str
    arguments: dict = {}
    result: Optional[dict] = None
    status: str = "ok"  # ok | error | timeout | retried


class AgentStep(BaseModel):
    step: int
    node: str
    summary: dict = {}


class AgentClaim(BaseModel):
    claim_text: str
    claim_type: str = "OBSERVATION"
    status: str = "INSUFFICIENT_EVIDENCE"
    result: str = "INSUFFICIENT_EVIDENCE"
    reason: Optional[str] = None
    verifier_version: Optional[str] = None
    evidence: List[dict] = []


class AgentAnswer(BaseModel):
    investigation_id: Optional[int] = None
    query: str
    status: str
    answer: str
    grounded: bool
    tool_calls: List[AgentToolCall] = []
    steps: List[AgentStep] = []
    claims: List[AgentClaim] = []
    events: List[dict] = []
    policy_sections: List[Any] = []


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    agent_result: AgentAnswer


# ---------------------------------------------------------------------------
# Verification API
# ---------------------------------------------------------------------------


class VerifyClaimResponse(VerificationOut):
    checks: Optional[dict] = None


class VerifyRequest(BaseModel):
    claim_text: str
    investigation_id: int
    claim_type: str = "OBSERVATION"
    video_id: Optional[int] = None
    timestamp: Optional[float] = None
    persist: bool = True
