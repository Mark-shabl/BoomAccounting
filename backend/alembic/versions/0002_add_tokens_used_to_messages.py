"""add tokens_used to messages

Revision ID: 0002_tokens_used
Revises: 0001_initial
Create Date: 2026-02-18

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_tokens_used"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("tokens_used", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "tokens_used")
