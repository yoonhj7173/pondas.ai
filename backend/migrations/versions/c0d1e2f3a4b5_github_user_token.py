"""GitHub user access token 저장(개인 계정 리포 생성용 — installation 토큰 403 quirk 해결).

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("github_connections", sa.Column("user_token_encrypted", sa.LargeBinary(), nullable=True))
    op.add_column("github_connections", sa.Column("refresh_token_encrypted", sa.LargeBinary(), nullable=True))
    op.add_column("github_connections", sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in ("token_expires_at", "refresh_token_encrypted", "user_token_encrypted"):
        op.drop_column("github_connections", col)
