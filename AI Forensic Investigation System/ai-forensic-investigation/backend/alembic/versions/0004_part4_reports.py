"""part 4 - human review + report generation (structured reports)

Revision ID: 0004_part4
Revises: 0003_part3
Create Date: 2026-08-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_part4"
down_revision: Union[str, None] = "0003_part3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("investigation_id", sa.Integer(), sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), server_default="DRAFT", nullable=False),
        sa.Column("is_final", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("storage_path", sa.String(512)),
        sa.Column("file_format", sa.String(20), server_default="pdf", nullable=False),
        sa.Column("generated_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_reports_investigation_id", "reports", ["investigation_id"])

    op.create_table(
        "report_review_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("claims.id")),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("original_text", sa.Text()),
        sa.Column("edited_text", sa.Text()),
        sa.Column("note", sa.Text()),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime()),
    )
    op.create_index("ix_report_review_decisions_report_id", "report_review_decisions", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_report_review_decisions_report_id", table_name="report_review_decisions")
    op.drop_table("report_review_decisions")
    op.drop_index("ix_reports_investigation_id", table_name="reports")
    op.drop_table("reports")
