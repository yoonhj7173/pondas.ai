"""allow role='event' in orchestrator_messages — task 종결 이벤트 라인(B1, 컨텍스트 허브)

태스크 종결을 지휘자 대화 이력에 이벤트 행으로 남긴다(다음 턴 히스토리 주입 + 채팅 회색 라인).
기존 CHECK(ck_orch_messages_role)가 user/orchestrator만 허용해 확장한다.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-07-14
"""

from __future__ import annotations

from alembic import op

revision = "d7e8f9a0b1c2"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None

_TABLE = "orchestrator_messages"
_CK = "ck_orch_messages_role"


def upgrade() -> None:
    op.drop_constraint(_CK, _TABLE, type_="check")
    op.create_check_constraint(_CK, _TABLE, "role IN ('user', 'orchestrator', 'event')")


def downgrade() -> None:
    # event 행이 남아 있으면 원 제약 복원이 실패하므로 먼저 지운다(이벤트 라인은 파생 데이터).
    op.execute(f"DELETE FROM {_TABLE} WHERE role = 'event'")
    op.drop_constraint(_CK, _TABLE, type_="check")
    op.create_check_constraint(_CK, _TABLE, "role IN ('user', 'orchestrator')")
