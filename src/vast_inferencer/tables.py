import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class InferenceEndpoint(Base):
    __tablename__ = "inference_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    vast_endpoint_name: Mapped[str] = mapped_column(String(200), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(128), unique=True)
    s3_endpoint_url: Mapped[str] = mapped_column(String(500))
    s3_bucket_name: Mapped[str] = mapped_column(String(200))
    s3_region: Mapped[str] = mapped_column(String(64), default="", server_default="")
    s3_access_key_id_enc: Mapped[str] = mapped_column(Text)
    s3_secret_access_key_enc: Mapped[str] = mapped_column(Text)
    webhook_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    webhook_secret_enc: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Generation(Base):
    __tablename__ = "generations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_generations_status",
        ),
        Index("ix_generations_project_created", "project_id", text("created_at DESC")),
        Index("ix_generations_endpoint_created", "inference_endpoint_id", text("created_at DESC")),
        Index("ix_generations_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    inference_endpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inference_endpoints.id"),
    )
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    workflow_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    webhook_extra_params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    webhook_url_override: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    qstash_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    sanitized_provider_request: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_provider_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    webhook_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    outputs: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    preprocess_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    postprocess_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vast_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forwarded_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    forwarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    forwarded_with_outputs: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
    )
