"""add notes table — user notes under Board (issue 4)

Per-project free-text notes (title + markdown body). Additive table, cascade on
project delete. Mirrors the goals/context_files shape.

Revision ID: b7c8d9e0f1a2
Revises: d5e6f7a8b9c0
Create Date: 2026-07-09 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), server_default="", nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notes_project", "notes", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_notes_project", table_name="notes")
    op.drop_table("notes")
