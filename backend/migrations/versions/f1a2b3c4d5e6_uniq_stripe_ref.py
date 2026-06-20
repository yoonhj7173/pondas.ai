"""partial unique index on credit_ledger.stripe_ref (concurrent double-credit, audit P0)

Stripe delivers webhooks at-least-once. The app-level `_already_posted` check
(PR #23) stops sequential retries, but two *concurrent* deliveries of the same
event both pass the SELECT then both INSERT → double credit. A partial unique
index `(stripe_ref) WHERE delta > 0` makes the DB the final arbiter.

Existing duplicate +credit rows (from the pre-PR#23 window) would block the
unique index, so we first NULL the stripe_ref on all but the earliest row per
(stripe_ref, delta>0) group. The rows are KEPT (append-only ledger) and balances
are UNCHANGED — only the dedup key is cleared on the bug-created duplicates.

Revision ID: f1a2b3c4d5e6
Revises: a1b2c3d4e5f6
Create Date: 2026-06-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) 중복 (stripe_ref, delta>0) 그룹에서 가장 이른 행만 남기고 나머지는 stripe_ref를 비운다.
    #    행은 보존(불변 장부) + 잔액 캐시 변동 없음 — 인덱스 생성을 막던 버그 데이터만 정리.
    op.execute(
        """
        UPDATE credit_ledger
        SET stripe_ref = NULL,
            note = COALESCE(note || ' ', '') || '[stripe_ref cleared: dup of ' || stripe_ref || ']'
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY stripe_ref ORDER BY created_at, id
                ) AS rn
                FROM credit_ledger
                WHERE stripe_ref IS NOT NULL AND delta > 0
            ) ranked
            WHERE ranked.rn > 1
        )
        """
    )
    # 2) 부분 유니크 인덱스 — 적립(delta>0)에 한해 stripe_ref 중복 차단(웹훅 멱등 DB 보증).
    op.execute(
        "CREATE UNIQUE INDEX uq_credit_ledger_stripe_ref "
        "ON credit_ledger (stripe_ref) WHERE delta > 0"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_credit_ledger_stripe_ref")
