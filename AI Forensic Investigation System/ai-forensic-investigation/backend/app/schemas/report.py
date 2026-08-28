"""Part 4 - Pydantic schemas for human review + report generation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Report sections (structured incident report)
# ---------------------------------------------------------------------------

REPORT_SECTION_TITLES: List[str] = [
    "Incident Information",
    "Executive Summary",
    "Incident Classification",
    "Verified Timeline",
    "Observed Persons/Objects",
    "Supporting Evidence",
    "Policy Assessment",
    "Inferred Information",
    "Unknown / Insufficient Evidence",
    "Recommendations",
    "Reviewer Decision",
]

REPORT_SECTIONS_ORDER: Dict[str, int] = {t: i for i, t in enumerate(REPORT_SECTION_TITLES)}


# ---------------------------------------------------------------------------
# Review decisions (human-in-the-loop)
# ---------------------------------------------------------------------------


class ReviewDecisionCreate(BaseModel):
    claim_id: Optional[int] = None
    action: str  # ACCEPT | REJECT | EDIT | UNCERTAIN
    edited_text: Optional[str] = None
    note: Optional[str] = None


class ReviewDecisionOut(BaseModel):
    id: int
    report_id: int
    claim_id: Optional[int] = None
    action: str
    original_text: Optional[str] = None
    edited_text: Optional[str] = None
    note: Optional[str] = None
    reviewer_user_id: Optional[int] = None
    reviewer_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_validator("reviewer_name", mode="before")
    @classmethod
    def _resolve_reviewer_name(cls, v, info):
        if v is not None:
            return v
        data = info.data
        reviewer = data.get("reviewer")
        return reviewer.name if reviewer else None


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class ReportOut(BaseModel):
    id: int
    investigation_id: int
    title: str
    status: str
    is_final: bool
    version: int
    storage_path: Optional[str] = None
    file_format: str = "markdown"
    generated_by_user_id: Optional[int] = None
    reviewed_by_user_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    investigation_title: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_validator("investigation_title", mode="before")
    @classmethod
    def _resolve_investigation_title(cls, v, info):
        if v is not None:
            return v
        data = info.data
        inv = data.get("investigation")
        return inv.title if inv else None


class ReportDetail(ReportOut):
    content: Optional[Dict[str, Any]] = None
    review_decisions: List[ReviewDecisionOut] = []

    @field_validator("content", mode="before")
    @classmethod
    def _parse_content(cls, v):
        if isinstance(v, str):
            import json

            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return v


class ReportGenerateRequest(BaseModel):
    title: Optional[str] = None


class ReportReviewOverall(BaseModel):
    decision: str  # APPROVE | REJECT | UNCERTAIN
    note: Optional[str] = None


class ReportQuery(BaseModel):
    start_time: Optional[float] = None
    end_time: Optional[float] = None


class ReportSectionsOutput(BaseModel):
    title: str
    sections: List[Dict[str, Any]]
