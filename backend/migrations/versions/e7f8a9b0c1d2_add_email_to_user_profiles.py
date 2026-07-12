"""add email column to user_profiles — Clerk primary email mirror

재접촉/마케팅용으로 Clerk의 primary 이메일을 우리 DB로 미러링. Clerk가 여전히
authoritative(인증). 온보딩 프로필 upsert 시 백엔드가 Clerk API로 best-effort 캡처.
Additive, nullable — 기존 행/흐름에 영향 없음.

Revision ID: e7f8a9b0c1d2
Revises: b7c8d9e0f1a2
Create Date: 2026-07-12 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("email", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "email")
