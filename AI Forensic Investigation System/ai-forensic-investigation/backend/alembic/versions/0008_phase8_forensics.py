"""phase 8 - forensic verification, timeline & reporting

Revision ID: 0008_phase8_forensics
Revises: 0007_phase7_investigator
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_phase8_forensics"
down_revision: Union[str, None] = "0007_phase7_investigator"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "forensic_timeline_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("investigation_runs.id"), nullable=False),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("timeline_event_id", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.Float(), nullable=False),
        sa.Column("end_timestamp", sa.Float()),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id")),
        sa.Column("session_id", sa.Integer()),
        sa.Column("event_id", sa.String(64)),
        sa.Column("track_id", sa.String(120)),
        sa.Column("object_class", sa.String(120)),
        sa.Column("event_type", sa.String(60)),
        sa.Column("description", sa.Text()),
        sa.Column("classification", sa.String(40), server_default="UNVERIFIED", nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("source", sa.String(40)),
        sa.Column("verification_status", sa.String(40), server_default="UNVERIFIED", nullable=False),
        sa.Column("evidence_ids", sa.Text()),
        sa.Column("quality_flags", sa.Text()),
        sa.Column("analytics_time", sa.DateTime()),
        sa.Column("storage_time", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_forensic_timeline_events_run_id", "forensic_timeline_events", ["run_id"])

    op.create_table(
        "forensic_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("investigation_runs.id"), nullable=False, unique=True),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("timeline", sa.Text()),
        sa.Column("findings", sa.Text()),
        sa.Column("correlations", sa.Text()),
        sa.Column("contradictions", sa.Text()),
        sa.Column("gaps", sa.Text()),
        sa.Column("relationships", sa.Text()),
        sa.Column("multi_camera", sa.Text()),
        sa.Column("sources", sa.Text()),
        sa.Column("metrics", sa.Text()),
        sa.Column("status", sa.String(40), server_default="PENDING_REVIEW", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "finding_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("investigation_runs.id"), nullable=False),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("finding_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("finding_snapshot", sa.Text()),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_finding_reviews_run_id", "finding_reviews", ["run_id"])

    op.create_table(
        "forensic_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("investigation_runs.id"), nullable=False),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("storage_path", sa.String(512)),
        sa.Column("file_format", sa.String(20), server_default="pdf", nullable=False),
        sa.Column("status", sa.String(40), server_default="GENERATED", nullable=False),
        sa.Column("generated_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_forensic_reports_run_id", "forensic_reports", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_forensic_reports_run_id", table_name="forensic_reports")
    op.drop_table("forensic_reports")
    op.drop_index("ix_finding_reviews_run_id", table_name="finding_reviews")
    op.drop_table("finding_reviews")
    op.drop_table("forensic_analyses")
    op.drop_index("ix_forensic_timeline_events_run_id", table_name="forensic_timeline_events")
    op.drop_table("forensic_timeline_events")