"""add cma columns

Revision ID: e70800386072
Revises: e9fd0d85cb5e
Create Date: 2026-06-14 13:37:34.201212

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e70800386072'
down_revision: Union[str, Sequence[str], None] = 'e9fd0d85cb5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — CMA Dev-engine pilot ids (D45). All nullable; null = crew/E2B path."""
    op.add_column("projects", sa.Column("cma_memory_store_id", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("cma_agent_id", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("cma_session_id", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agents", "cma_session_id")
    op.drop_column("agents", "cma_agent_id")
    op.drop_column("projects", "cma_memory_store_id")
