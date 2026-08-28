"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="INVESTIGATOR"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("camera_name", sa.String(255), nullable=False),
        sa.Column("location", sa.String(255)),
        sa.Column("description", sa.Text()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id")),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("fps", sa.Float()),
        sa.Column("codec", sa.String(100)),
        sa.Column("recording_date", sa.DateTime()),
        sa.Column("start_time", sa.DateTime()),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(50), server_default="UPLOADED"),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("uploaded_at", sa.DateTime()),
    )

    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("status", sa.String(50), server_default="QUEUED"),
        sa.Column("stage", sa.String(50)),
        sa.Column("progress", sa.Float(), server_default=sa.text("0.0")),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "clips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(50), nullable=False, unique=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id")),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("storage_path", sa.String(512)),
        sa.Column("thumbnail_path", sa.String(512)),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "detections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clip_id", sa.Integer(), sa.ForeignKey("clips.id"), nullable=False),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id")),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("bounding_box", sa.Text(), nullable=False),
        sa.Column("frame_number", sa.Integer()),
        sa.Column("timestamp", sa.Float()),
        sa.Column("detection_confidence", sa.Float()),
        sa.Column("tracking_id", sa.String(100)),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("clip_id", sa.Integer(), sa.ForeignKey("clips.id")),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("start_time", sa.Float()),
        sa.Column("end_time", sa.Float()),
        sa.Column("confidence", sa.Float()),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(100)),
        sa.Column("entity_id", sa.Integer()),
        sa.Column("details", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_index("ix_detections_video_id", "detections", ["video_id"])
    op.create_index("ix_events_video_id", "events", ["video_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("events")
    op.drop_table("detections")
    op.drop_table("clips")
    op.drop_table("processing_jobs")
    op.drop_table("videos")
    op.drop_table("cameras")
    op.drop_table("users")
