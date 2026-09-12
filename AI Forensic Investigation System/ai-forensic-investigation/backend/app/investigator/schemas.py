"""Phase 7 - API contracts for controlled investigation runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RunStartRequest(BaseModel):
    """Start a Phase 7 investigation run.

    ``query`` defaults to the investigation's objective when omitted.
    ``require_review`` overrides the configured AGENT_REQUIRE_HUMAN_REVIEW for
    this single run (used by automation / tests).
    """

    query: Optional[str] = Field(default=None, min_length=1, max_length=500)
    require_review: Optional[bool] = None


class RunOut(BaseModel):
    run_id: int
    investigation_id: int
    status: str
    query: str
    classification: Dict[str, Any] = Field(default_factory=dict)
    plan: List[Dict[str, Any]] = Field(default_factory=list)
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    claims: List[Dict[str, Any]] = Field(default_factory=list)
    result: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class RunRow(BaseModel):
    id: int
    investigation_id: int
    status: str
    query: str
    metrics: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class RunListResponse(BaseModel):
    runs: List[RunRow] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT|CANCEL)$")
    note: Optional[str] = Field(default=None, max_length=1000)