"""phase 7 - controlled investigation runs

Revision ID: 0007_phase7_investigator
Revises: 0006_phase5_evidence
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_phase7_investigator"
down_revision: Union[str, None] = "0006_phase5_evidence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "investigation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("status", sa.String(50), server_default="CREATED", nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("classification", sa.Text()),
        sa.Column("plan", sa.Text()),
        sa.Column("steps", sa.Text()),
        sa.Column("claims", sa.Text()),
        sa.Column("result", sa.Text()),
        sa.Column("metrics", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_investigation_runs_investigation_id", "investigation_runs", ["investigation_id"])


def downgrade() -> None:
    op.drop_index("ix_investigation_runs_investigation_id", table_name="investigation_runs")
    op.drop_table("investigation_runs")