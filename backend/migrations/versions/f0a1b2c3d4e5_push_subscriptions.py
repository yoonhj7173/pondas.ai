"""Web Push 구독(item 39, D56⑤).

Revision ID: f0a1b2c3d4e5
Revises: e8f9a0b1c2d3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "f0a1b2c3d4e5"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("keys", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_push_subscriptions_user", "push_subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_user", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
