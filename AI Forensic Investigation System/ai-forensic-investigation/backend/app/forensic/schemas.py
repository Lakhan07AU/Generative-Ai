"""Phase 8 forensic API request/response contracts."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class FindingReviewAction(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    MARKED_UNCERTAIN = "MARKED_UNCERTAIN"
    REQUESTED_MORE_EVIDENCE = "REQUESTED_MORE_EVIDENCE"


class FindingReviewRequest(BaseModel):
    action: FindingReviewAction
    comment: str = Field(default="", max_length=2000)


def snapshot_of_finding(analysis: dict, finding_id: str) -> dict:
    for finding in analysis.get("findings") or []:
        if finding.get("finding_id") == finding_id:
            return finding
    return {}