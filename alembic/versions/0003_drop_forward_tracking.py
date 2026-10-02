"""drop webhook forward tracking from generations

Revision ID: 0003_drop_forward_tracking
Revises: 0002_drop_project_endpoint
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_drop_forward_tracking"
down_revision: str | None = "0002_drop_project_endpoint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("generations", "forwarded_with_outputs")
    op.drop_column("generations", "forwarded_at")
    op.drop_column("generations", "forwarded_status")


def downgrade() -> None:
    op.add_column(
        "generations",
        sa.Column("forwarded_status", sa.String(32), nullable=True),
    )
    op.add_column(
        "generations",
        sa.Column("forwarded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "generations",
        sa.Column(
            "forwarded_with_outputs",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
