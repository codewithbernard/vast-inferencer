"""drop inference endpoint assignment from projects

Revision ID: 0002_drop_project_endpoint
Revises: 0001_initial
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_drop_project_endpoint"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_projects_inference_endpoint_id", table_name="projects")
    op.drop_constraint("fk_projects_inference_endpoint_id", "projects", type_="foreignkey")
    op.drop_column("projects", "inference_endpoint_id")


def downgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("inference_endpoint_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_projects_inference_endpoint_id",
        "projects",
        "inference_endpoints",
        ["inference_endpoint_id"],
        ["id"],
    )
    op.create_index(
        "ix_projects_inference_endpoint_id",
        "projects",
        ["inference_endpoint_id"],
    )
