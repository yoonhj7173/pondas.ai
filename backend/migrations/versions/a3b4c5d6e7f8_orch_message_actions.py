"""add actions column to orchestrator_messages — orchestrator action memory (QA-05)

지휘자 히스토리 중립화(#76)로 지휘자가 자기 행동을 잊는 부작용("트리거한 적 없다" 가스라이팅).
그 턴의 행동 요약(ctx.actions JSON)을 저장해 히스토리 마커에 사실로 남긴다.
Additive, nullable — 기존 행은 NULL(기존 마커로 폴백).

Revision ID: a3b4c5d6e7f8
Revises: e7f8a9b0c1d2
Create Date: 2026-07-13 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orchestrator_messages", sa.Column("actions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("orchestrator_messages", "actions")
