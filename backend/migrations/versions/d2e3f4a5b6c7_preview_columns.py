"""preview service columns on projects (Phase 2 closure, D49)

Additive only — 4 nullable columns for the live-preview sandbox lifecycle,
independent of the build workspace (sandbox_id/*). Safe on live prod.
`preview_enabled` stays a config default (OFF) — flipped ON at item 34, same
pattern as billing_enabled.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("preview_sandbox_id", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("preview_status", sa.Text(), nullable=False, server_default="none"))
    op.add_column("projects", sa.Column("preview_version_no", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("preview_last_active_at", sa.DateTime(), nullable=True))
    op.create_check_constraint(
        "ck_projects_preview_status",
        "projects",
        "preview_status IN ('none', 'starting', 'ready', 'error', 'paused')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_projects_preview_status", "projects", type_="check")
    op.drop_column("projects", "preview_last_active_at")
    op.drop_column("projects", "preview_version_no")
    op.drop_column("projects", "preview_status")
    op.drop_column("projects", "preview_sandbox_id")
