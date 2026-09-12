"""phase 5 - live evidence capture + durable forensic evidence + indexing

Revision ID: 0006_phase5_evidence
Revises: 0005_phase1_live
Create Date: 2026-09-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_phase5_evidence"
down_revision: Union[str, None] = "0005_phase1_live"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vlm_observation_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observation_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("request_id", sa.String(64)),
        sa.Column("camera_id", sa.Integer()),
        sa.Column("session_id", sa.Integer()),
        sa.Column("trigger", sa.String(40)),
        sa.Column("trigger_detail", sa.String(100)),
        sa.Column("summary", sa.Text()),
        sa.Column("items", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("model", sa.String(100)),
        sa.Column("provider_mode", sa.String(20)),
        sa.Column("source_frames", sa.Text()),
        sa.Column("window_start", sa.Float()),
        sa.Column("window_end", sa.Float()),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "forensic_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("evidence_type", sa.String(40), nullable=False),
        sa.Column("source", sa.String(40), server_default="DERIVED", nullable=False),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id")),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("camera_sessions.id")),
        sa.Column("event_id", sa.String(255)),
        sa.Column("event_type", sa.String(100)),
        sa.Column("tracking_id", sa.String(100)),
        sa.Column("frame_sequence", sa.Integer()),
        sa.Column("frame_timestamp", sa.Float()),
        sa.Column("window_start", sa.Float()),
        sa.Column("window_end", sa.Float()),
        sa.Column("vlm_observation_id", sa.String(64)),
        sa.Column("source_frame_ids", sa.Text()),
        sa.Column("captured_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("storage_path", sa.String(512)),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("sha256", sa.String(64)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("content_text", sa.Text()),
        sa.Column("metadata", sa.Text()),
        sa.Column("provenance", sa.Text()),
        sa.Column("index_status", sa.String(20), server_default="PENDING", nullable=False),
        sa.Column("index_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_index_attempt_at", sa.DateTime()),
        sa.Column("index_error", sa.Text()),
        sa.Column("indexed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_forensic_evidence_camera_id", "forensic_evidence", ["camera_id"])
    op.create_index("ix_forensic_evidence_session_id", "forensic_evidence", ["session_id"])
    op.create_index(
        "ix_forensic_evidence_captured_at", "forensic_evidence", ["captured_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_forensic_evidence_captured_at", table_name="forensic_evidence")
    op.drop_index("ix_forensic_evidence_session_id", table_name="forensic_evidence")
    op.drop_index("ix_forensic_evidence_camera_id", table_name="forensic_evidence")
    op.drop_table("forensic_evidence")
    op.drop_table("vlm_observation_records")