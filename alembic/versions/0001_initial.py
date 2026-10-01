"""create inference endpoints, projects, and generations

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inference_endpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("vast_endpoint_name", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("vast_endpoint_name", name="uq_inference_endpoints_vast_endpoint_name"),
    )
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("inference_endpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("s3_endpoint_url", sa.String(500), nullable=False),
        sa.Column("s3_bucket_name", sa.String(200), nullable=False),
        sa.Column("s3_region", sa.String(64), nullable=False, server_default=""),
        sa.Column("s3_access_key_id_enc", sa.Text(), nullable=False),
        sa.Column("s3_secret_access_key_enc", sa.Text(), nullable=False),
        sa.Column("webhook_url", sa.String(2000), nullable=True),
        sa.Column("webhook_secret_enc", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["inference_endpoint_id"],
            ["inference_endpoints.id"],
            name="fk_projects_inference_endpoint_id",
        ),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
    )
    op.create_index(
        "ix_projects_inference_endpoint_id",
        "projects",
        ["inference_endpoint_id"],
    )
    op.create_table(
        "generations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inference_endpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("workflow_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "webhook_extra_params",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("webhook_url_override", sa.String(2000), nullable=True),
        sa.Column("qstash_message_id", sa.String(200), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sanitized_provider_request", postgresql.JSONB(), nullable=True),
        sa.Column("raw_provider_response", postgresql.JSONB(), nullable=True),
        sa.Column("webhook_payload", postgresql.JSONB(), nullable=True),
        sa.Column("outputs", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", postgresql.JSONB(), nullable=True),
        sa.Column("preprocess_ms", sa.Integer(), nullable=True),
        sa.Column("generation_ms", sa.Integer(), nullable=True),
        sa.Column("postprocess_ms", sa.Integer(), nullable=True),
        sa.Column("total_ms", sa.Integer(), nullable=True),
        sa.Column("vast_latency_ms", sa.Integer(), nullable=True),
        sa.Column("forwarded_status", sa.String(32), nullable=True),
        sa.Column("forwarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "forwarded_with_outputs",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_generations_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_generations_project_id",
        ),
        sa.ForeignKeyConstraint(
            ["inference_endpoint_id"],
            ["inference_endpoints.id"],
            name="fk_generations_inference_endpoint_id",
        ),
    )
    op.execute(
        "CREATE INDEX ix_generations_project_created "
        "ON generations (project_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_generations_endpoint_created "
        "ON generations (inference_endpoint_id, created_at DESC)"
    )
    op.create_index("ix_generations_status", "generations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_generations_status", table_name="generations")
    op.drop_index("ix_generations_endpoint_created", table_name="generations")
    op.drop_index("ix_generations_project_created", table_name="generations")
    op.drop_table("generations")
    op.drop_index("ix_projects_inference_endpoint_id", table_name="projects")
    op.drop_table("projects")
    op.drop_table("inference_endpoints")
