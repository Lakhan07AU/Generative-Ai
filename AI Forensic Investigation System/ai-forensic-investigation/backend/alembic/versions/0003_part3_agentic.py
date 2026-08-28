"""part 3 - agentic investigation / evidence verification / claim traceability / timeline

Revision ID: 0003_part3
Revises: 0002_part2
Create Date: 2026-08-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_part3"
down_revision: Union[str, None] = "0002_part2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id")),
        sa.Column("status", sa.String(50), server_default="OPEN", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(60), server_default="OBSERVATION", nullable=False),
        sa.Column("status", sa.String(60), server_default="OPEN", nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_claims_investigation_id", "claims", ["investigation_id"])

    op.create_table(
        "claim_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("clip_id", sa.Integer(), sa.ForeignKey("clips.id")),
        sa.Column("frame_id", sa.Integer()),
        sa.Column("timestamp", sa.Float()),
        sa.Column("evidence_type", sa.String(60)),
        sa.Column("relevance_score", sa.Float()),
    )
    op.create_index("ix_claim_evidence_claim_id", "claim_evidence", ["claim_id"])

    op.create_table(
        "verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("checks", sa.Text()),
        sa.Column("result", sa.String(60), server_default="INSUFFICIENT_EVIDENCE", nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("verifier_version", sa.String(50)),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_verifications_claim_id", "verifications", ["claim_id"])

    op.create_table(
        "timeline_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("timestamp", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(60), server_default="UNVERIFIED", nullable=False),
        sa.Column("evidence_ids", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_timeline_events_investigation_id", "timeline_events", ["investigation_id"])


def downgrade() -> None:
    op.drop_table("timeline_events")
    op.drop_table("verifications")
    op.drop_table("claim_evidence")
    op.drop_table("claims")
    op.drop_table("investigations")
