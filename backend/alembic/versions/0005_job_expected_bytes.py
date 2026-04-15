"""model_download_jobs.expected_bytes from Hugging Face metadata

Revision ID: 0005_job_expected_bytes
Revises: 0004_shared_models
Create Date: 2026-04-14

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_job_expected_bytes"
down_revision = "0004_shared_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_download_jobs",
        sa.Column("expected_bytes", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_download_jobs", "expected_bytes")
