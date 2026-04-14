"""shared models: owner nullable, unique hf_repo+hf_filename, merge duplicates

Revision ID: 0004_shared_models
Revises: 0003_size_bytes_bigint
Create Date: 2026-03-17

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "0004_shared_models"
down_revision = "0003_size_bytes_bigint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Make owner_user_id nullable
    op.alter_column(
        "models",
        "owner_user_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # 2. Merge duplicates: for each (hf_repo, hf_filename) keep one model
    conn = op.get_bind()
    rows = conn.execute(
        text("""
            SELECT hf_repo, hf_filename, GROUP_CONCAT(id ORDER BY id) AS ids
            FROM models
            GROUP BY hf_repo, hf_filename
            HAVING COUNT(*) > 1
        """)
    ).fetchall()

    for hf_repo, hf_filename, ids_str in rows:
        ids = [int(x) for x in ids_str.split(",")]
        kept_id = min(ids)
        dup_ids = [i for i in ids if i != kept_id]

        for dup_id in dup_ids:
            conn.execute(text("UPDATE chats SET model_id = :k WHERE model_id = :d"), {"k": kept_id, "d": dup_id})
            conn.execute(
                text("UPDATE model_download_jobs SET model_id = :k WHERE model_id = :d"),
                {"k": kept_id, "d": dup_id},
            )
            conn.execute(text("DELETE FROM models WHERE id = :d"), {"d": dup_id})

    # 3. Add unique constraint
    op.create_unique_constraint(
        "uq_models_hf_repo_filename",
        "models",
        ["hf_repo", "hf_filename"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_models_hf_repo_filename", "models", type_="unique")
    conn = op.get_bind()
    conn.execute(text("UPDATE models SET owner_user_id = (SELECT id FROM users LIMIT 1) WHERE owner_user_id IS NULL"))
    op.alter_column(
        "models",
        "owner_user_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
