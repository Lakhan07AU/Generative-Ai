"""phase 1 - live mobile camera (WebRTC) session tracking

Revision ID: 0005_phase1_live
Revises: 0004_part4
Create Date: 2026-09-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_phase1_live"
down_revision: Union[str, None] = "0004_part4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extend cameras with live-capture metadata (backfilled for existing rows).
    op.add_column("cameras", sa.Column("camera_type", sa.String(50), server_default="CCTV", nullable=False))
    op.add_column("cameras", sa.Column("stream_source", sa.String(255)))
    op.add_column("cameras", sa.Column("is_live", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("cameras", sa.Column("stream_status", sa.String(50), server_default="OFFLINE", nullable=False))

    op.create_table(
        "camera_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id"), nullable=False),
        sa.Column("status", sa.String(50), server_default="CONNECTING", nullable=False),
        sa.Column("transport", sa.String(20), server_default="webrtc", nullable=False),
        sa.Column("fps_target", sa.Float(), server_default="5.0", nullable=False),
        sa.Column("started_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("stopped_at", sa.DateTime()),
        sa.Column("error", sa.Text()),
        sa.Column("frames_received", sa.Integer(), server_default="0", nullable=False),
        sa.Column("frames_sampled", sa.Integer(), server_default="0", nullable=False),
        sa.Column("frames_buffered", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latest_frame_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_camera_sessions_camera_id", "camera_sessions", ["camera_id"])


def downgrade() -> None:
    op.drop_index("ix_camera_sessions_camera_id", table_name="camera_sessions")
    op.drop_table("camera_sessions")

    op.drop_column("cameras", "stream_status")
    op.drop_column("cameras", "is_live")
    op.drop_column("cameras", "stream_source")
    op.drop_column("cameras", "camera_type")