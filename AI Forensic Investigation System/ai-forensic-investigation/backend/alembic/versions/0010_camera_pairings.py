"""single-use QR camera pairings (device-to-camera binding)

Revision ID: 0010_camera_pairings
Revises: 0009_camera_automation_fields
Create Date: 2026-09-28

Adds a ``camera_pairings`` table for QR device pairing. A pairing is created
by the desktop investigator, rendered as a QR code, scanned by the mobile /
camera UI, and presented once over the signaling WebSocket. The row enforces
creator binding, per-camera binding, expiry and single-use consumption, so a
printed/leaked QR cannot be replayed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_camera_pairings"
down_revision: Union[str, None] = "0009_camera_automation_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "camera_pairings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pairing_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_camera_pairings_camera_id", "camera_pairings", ["camera_id"])


def downgrade() -> None:
    op.drop_index("ix_camera_pairings_camera_id", table_name="camera_pairings")
    op.drop_index("ix_camera_pairings_pairing_id", table_name="camera_pairings")
    op.drop_table("camera_pairings")