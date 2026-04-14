"""size_bytes and progress_bytes to BIGINT (до 100 GB+)

Revision ID: 0003_size_bytes_bigint
Revises: 0002_tokens_used
Create Date: 2026-03-17

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_size_bytes_bigint"
down_revision = "0002_tokens_used"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "models",
        "size_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    op.alter_column(
        "model_download_jobs",
        "progress_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "model_download_jobs",
        "progress_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "models",
        "size_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
