"""flip preview_enabled ON — Live Preview go-live (Phase 2, D49/item 34)

The Phase 2 closure launch flip. With this ON: the theater's POST /preview/start
materializes the project's current version into an on-demand E2B sandbox and
serves the running app; the beat job idle-pauses previews. Core validated live
(real app served into the theater iframe on live E2B). Durable — seed never
touches preview_enabled. Reversible via downgrade (falls back to _DEFAULTS 'false').

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-07-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO config (key, value) VALUES ('preview_enabled', 'true') "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    )


def downgrade() -> None:
    # 행 삭제 → _DEFAULTS의 'false'로 폴백(프리뷰 OFF).
    op.execute("DELETE FROM config WHERE key = 'preview_enabled'")
