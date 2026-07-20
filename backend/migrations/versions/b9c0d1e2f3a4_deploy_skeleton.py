"""Deploy 골격(item 37, D60) — projects 배포 컬럼 + project_secrets(암호화 at rest).

Revision ID: b9c0d1e2f3a4
Revises: f0a1b2c3d4e5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "b9c0d1e2f3a4"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("deploy_provider_id", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("deploy_url", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("deploy_domain", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("deploy_status", sa.Text(), nullable=False, server_default="none"))
    op.add_column("projects", sa.Column("deployed_version_no", sa.Integer(), nullable=True))
    op.create_table(
        "project_secrets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("project_id", "key", name="uq_project_secrets_key"),
    )


def downgrade() -> None:
    op.drop_table("project_secrets")
    for col in ("deployed_version_no", "deploy_status", "deploy_domain", "deploy_url", "deploy_provider_id"):
        op.drop_column("projects", col)
