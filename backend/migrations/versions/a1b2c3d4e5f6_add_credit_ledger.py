"""add credit accounts + ledger (billing D46)

Revision ID: a1b2c3d4e5f6
Revises: e70800386072
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e70800386072'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PLANS = ("free", "starter", "pro", "studio")
_REASONS = (
    "signup_grant", "monthly_refill", "topup",
    "task_charge", "refund_system_failure", "adjustment",
)


def upgrade() -> None:
    """Upgrade schema — credit wallet + append-only ledger (D46)."""
    op.create_table(
        "credit_accounts",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("plan", sa.Text(), nullable=False, server_default="free"),
        sa.Column("monthly_allowance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("allowance_resets_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spending_cap_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("signup_granted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("stripe_customer_id", sa.Text(), nullable=True),
        sa.Column("stripe_subscription_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "plan IN " + str(_PLANS), name="ck_credit_accounts_plan"
        ),
    )
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("stripe_ref", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "reason IN " + str(_REASONS), name="ck_credit_ledger_reason"
        ),
    )
    op.create_index(
        "ix_credit_ledger_user", "credit_ledger",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_credit_ledger_user", table_name="credit_ledger")
    op.drop_table("credit_ledger")
    op.drop_table("credit_accounts")
