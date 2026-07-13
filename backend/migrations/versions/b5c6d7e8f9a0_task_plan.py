"""add plan column to tasks — agent subtask checklist (QA-06 stage 2)

dev/design 에이전트가 작업 시작 시 세우는 서브태스크 plan [{title, done}].
러너의 update_plan 도구가 갱신하고 패널이 체크리스트(✓✓▸○)로 렌더.
Additive, nullable — 기존 행/흐름 무영향.

Revision ID: b5c6d7e8f9a0
Revises: a3b4c5d6e7f8
Create Date: 2026-07-13 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("plan", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "plan")
