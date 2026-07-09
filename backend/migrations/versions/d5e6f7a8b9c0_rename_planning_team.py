"""rename the planning team display name: Product Planning -> Product Management (issue 2-1)

The template_key stays 'planning' (emoji/carpet maps key off it). Only the display
name changes. catalog.py + the frontend fallback are the source going forward; this
migration renames rows that already exist so live teams update on deploy (seed does
not run on boot, only migrations do). Idempotent + reversible.

Revision ID: d5e6f7a8b9c0
Revises: e3f4a5b6c7d8
Create Date: 2026-07-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE team_templates SET name = 'Product Management' "
        "WHERE key = 'planning' AND name = 'Product Planning'"
    )
    op.execute(
        "UPDATE teams SET name = 'Product Management' "
        "WHERE template_key = 'planning' AND name = 'Product Planning'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE team_templates SET name = 'Product Planning' "
        "WHERE key = 'planning' AND name = 'Product Management'"
    )
    op.execute(
        "UPDATE teams SET name = 'Product Planning' "
        "WHERE template_key = 'planning' AND name = 'Product Management'"
    )
