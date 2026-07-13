"""remove visual_designer role from catalog — Design team = Product Designer only

Product Designer가 디자인시스템+정적 HTML 목업으로 비주얼 작업까지 흡수(역할 단순화).
agent_templates의 visual_designer 행을 제거해 "add agent" 모달에서 사라지게 한다.
기존에 유저가 이미 만든 visual_designer *에이전트*(자기 role_instructions 복사본 보유)는
건드리지 않는다 — 계속 동작. seed는 upsert만 하므로 카탈로그에서 뺀 것만으로는 이 행이 안
지워져 별도 삭제가 필요.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-07-13 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, Sequence[str], None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM agent_templates WHERE role_key = 'visual_designer'")


def downgrade() -> None:
    # seed.py가 재삽입하므로 downgrade는 no-op(카탈로그에서 이미 제거됨).
    pass
