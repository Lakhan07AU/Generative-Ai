"""part 2 - multimodal ai / video rag / policy rag

Revision ID: 0002_part2
Revises: 0001_initial
Create Date: 2026-08-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_part2"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clip_descriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clip_id", sa.Integer(), sa.ForeignKey("clips.id"), nullable=False),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("objects", sa.Text()),
        sa.Column("observable_actions", sa.Text()),
        sa.Column("location_context", sa.Text()),
        sa.Column("transcript_reference", sa.Text()),
        sa.Column("source", sa.String(50), server_default="simulation"),
        sa.Column("confidence", sa.Float()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_clip_descriptions_video_id", "clip_descriptions", ["video_id"])

    op.create_table(
        "transcripts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("clip_id", sa.Integer(), sa.ForeignKey("clips.id")),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_transcripts_video_id", "transcripts", ["video_id"])

    op.create_table(
        "policy_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("policy_id", sa.String(64), nullable=False, unique=True),
        sa.Column("document_name", sa.String(255), nullable=False),
        sa.Column("filename", sa.String(255)),
        sa.Column("storage_path", sa.String(512)),
        sa.Column("source_format", sa.String(20)),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(50), server_default="INDEXED"),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "policy_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("policy_documents.id"), nullable=False),
        sa.Column("section", sa.String(255)),
        sa.Column("page", sa.Integer()),
        sa.Column("chunk_index", sa.Integer()),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_policy_chunks_policy_id", "policy_chunks", ["policy_id"])

    op.create_table(
        "findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id")),
        sa.Column("clip_id", sa.Integer(), sa.ForeignKey("clips.id")),
        sa.Column("finding_status", sa.String(30), nullable=False, server_default="UNKNOWN"),
        sa.Column("finding_type", sa.String(60)),
        sa.Column("question", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("confidence", sa.Float()),
        sa.Column("retrieval_score", sa.Float()),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("policy_documents.id")),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_findings_video_id", "findings", ["video_id"])


def downgrade() -> None:
    op.drop_table("findings")
    op.drop_table("policy_chunks")
    op.drop_table("policy_documents")
    op.drop_table("transcripts")
    op.drop_table("clip_descriptions")
