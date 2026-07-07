"""project_files + workspace_versions (Phase 2 closure, D50)

Additive only — two new tables underpinning the canonical project file state and
per-project version snapshots. No changes to existing tables; safe on live prod
(auto-runs on web boot). The write path (worker snapshot) populates these going
forward; existing outputs endpoints are untouched.

Revision ID: c1d2e3f4a5b6
Revises: b8c9d0e1f2a3
Create Date: 2026-07-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("output_id", UUID(as_uuid=True),
                  sa.ForeignKey("outputs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("updated_by_task_id", UUID(as_uuid=True),
                  sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "path", name="uq_project_files_path"),
    )
    op.create_index("ix_project_files_project", "project_files", ["project_id"])

    op.create_table(
        "workspace_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("task_id", UUID(as_uuid=True),
                  sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("manifest", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "version_no", name="uq_workspace_versions_no"),
    )
    op.create_index("ix_workspace_versions_project", "workspace_versions", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_versions_project", table_name="workspace_versions")
    op.drop_table("workspace_versions")
    op.drop_index("ix_project_files_project", table_name="project_files")
    op.drop_table("project_files")
