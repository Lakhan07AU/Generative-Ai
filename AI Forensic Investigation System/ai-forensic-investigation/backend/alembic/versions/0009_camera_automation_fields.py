"""camera automation fields: auto-processing, ONVIF/RTSP identity, health

Revision ID: 0009_camera_automation_fields
Revises: 0008_phase8_forensics
Create Date: 2026-09-28

Adds the schema the CCTV automation feature needs without touching existing
cameras rows:

  * ``auto_process``     - supervisor flag: keep this camera's stream running
  * ``onvif_host``       - ONVIF discovery target (host[:port])
  * ``onvif_username``   - ONVIF WS-Username token user (shadowed in API output)
  * ``credential_ref``   - opaque reference to rotated/stored credentials
  * ``rtsp_url``         - main RTSP stream URL
  * ``rtsp_url_alt``     - sub (backup) RTSP stream URL
  * ``last_seen_at``     - last framed/valid contact from the camera
  * ``health_status``    - ONLINE | DEGRADED | OFFLINE | PENDING
  * ``last_error``       - last supervisor error text (no secrets)
  * ``reconnect_attempts`` - consecutive reconnection attempt counter
  * ``max_processing_fps`` - optional per-camera processing budget cap

All new columns are nullable or have server defaults, so the migration is a
pure additive ALTER on the existing ``cameras`` table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_camera_automation_fields"
down_revision: Union[str, None] = "0008_phase8_forensics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("auto_process", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("cameras", sa.Column("onvif_host", sa.String(255), nullable=True))
    op.add_column("cameras", sa.Column("onvif_username", sa.String(255), nullable=True))
    op.add_column("cameras", sa.Column("credential_ref", sa.String(512), nullable=True))
    op.add_column("cameras", sa.Column("rtsp_url", sa.String(512), nullable=True))
    op.add_column("cameras", sa.Column("rtsp_url_alt", sa.String(512), nullable=True))
    op.add_column("cameras", sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    op.add_column("cameras", sa.Column("health_status", sa.String(50), server_default="OFFLINE", nullable=False))
    op.add_column("cameras", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("cameras", sa.Column("reconnect_attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("cameras", sa.Column("max_processing_fps", sa.Float(), nullable=True))
    op.create_index("ix_cameras_auto_process", "cameras", ["auto_process"])


def downgrade() -> None:
    op.drop_index("ix_cameras_auto_process", table_name="cameras")
    op.drop_column("cameras", "max_processing_fps")
    op.drop_column("cameras", "reconnect_attempts")
    op.drop_column("cameras", "last_error")
    op.drop_column("cameras", "health_status")
    op.drop_column("cameras", "last_seen_at")
    op.drop_column("cameras", "rtsp_url_alt")
    op.drop_column("cameras", "rtsp_url")
    op.drop_column("cameras", "credential_ref")
    op.drop_column("cameras", "onvif_username")
    op.drop_column("cameras", "onvif_host")
    op.drop_column("cameras", "auto_process")