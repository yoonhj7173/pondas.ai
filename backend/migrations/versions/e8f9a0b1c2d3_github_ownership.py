"""GitHub 소유권(item 36, D61) — github_connections + 버전 라벨/푸시 상태 + 프로젝트 리포.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_connections",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column("projects", sa.Column("repo_full_name", sa.Text(), nullable=True))
    op.add_column("workspace_versions", sa.Column("label", sa.Text(), nullable=True))
    op.add_column("workspace_versions", sa.Column("commit_sha", sa.Text(), nullable=True))
    op.add_column("workspace_versions", sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_versions", "pushed_at")
    op.drop_column("workspace_versions", "commit_sha")
    op.drop_column("workspace_versions", "label")
    op.drop_column("projects", "repo_full_name")
    op.drop_table("github_connections")
