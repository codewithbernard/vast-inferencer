import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, field_validator

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
GenerationStatus = Literal["queued", "running", "completed", "failed"]


def _json_object(value: dict[str, Any]) -> dict[str, Any]:
    json.dumps(value)
    return value


class InferenceEndpointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    vast_endpoint_name: str = Field(min_length=1, max_length=200)
    enabled: bool = True

    @field_validator("name", "vast_endpoint_name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be blank")
        return text


class InferenceEndpointUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    vast_endpoint_name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None

    @field_validator("name", "vast_endpoint_name")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be blank")
        return text


class InferenceEndpointOut(BaseModel):
    id: UUID
    name: str
    vast_endpoint_name: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class S3Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_key_id: SecretStr = Field(min_length=1)
    secret_access_key: SecretStr = Field(min_length=1)
    endpoint_url: str = Field(min_length=1, max_length=500)
    bucket_name: str = Field(min_length=1, max_length=200)
    region: str = Field(default="", max_length=64)

    @field_validator("access_key_id", "secret_access_key")
    @classmethod
    def strip_secret(cls, value: SecretStr) -> SecretStr:
        text = value.get_secret_value().strip()
        if not text:
            raise ValueError("must not be blank")
        return SecretStr(text)

    @field_validator("endpoint_url", "bucket_name", "region")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class SanitizedS3(BaseModel):
    access_key_id: Literal["[REDACTED]"] = "[REDACTED]"
    secret_access_key: Literal["[REDACTED]"] = "[REDACTED]"
    endpoint_url: str
    bucket_name: str
    region: str


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=128)
    s3: S3Input
    webhook_url: AnyHttpUrl | None = None
    webhook_secret: SecretStr | None = None

    @field_validator("name", "slug")
    @classmethod
    def strip_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be blank")
        return text

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, value: str) -> str:
        if not _SLUG.match(value):
            raise ValueError("slug must be lowercase letters, numbers, and hyphens")
        return value


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=128)
    s3_endpoint_url: str | None = Field(default=None, min_length=1, max_length=500)
    s3_bucket_name: str | None = Field(default=None, min_length=1, max_length=200)
    s3_region: str | None = Field(default=None, max_length=64)
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    webhook_url: AnyHttpUrl | None = None
    webhook_secret: SecretStr | None = None

    @field_validator("s3_access_key_id", "s3_secret_access_key", "webhook_secret")
    @classmethod
    def secret_not_blank(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        if not value.get_secret_value().strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("name", "slug", "s3_endpoint_url", "s3_bucket_name", "s3_region")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _SLUG.match(value):
            raise ValueError("slug must be lowercase letters, numbers, and hyphens")
        return value


class ProjectOut(BaseModel):
    id: UUID
    name: str
    slug: str
    s3: SanitizedS3
    webhook_url: str | None
    webhook_secret_set: bool
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectOut):
    recent_generations: list["GenerationListItem"]


class InferenceEndpointDetail(InferenceEndpointOut):
    recent_generations: list["GenerationListItem"]


class GenerationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vast_endpoint_name: str = Field(min_length=1, max_length=200)
    workflow_json: dict[str, Any] = Field(min_length=1)
    webhook_extra_params: dict[str, Any] = Field(default_factory=dict)
    webhook_url: AnyHttpUrl | None = None

    @field_validator("vast_endpoint_name")
    @classmethod
    def strip_endpoint_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be blank")
        return text

    @field_validator("workflow_json", "webhook_extra_params")
    @classmethod
    def values_must_be_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _json_object(value)


class GenerationCreateCompat(GenerationCreate):
    project_id: str = Field(min_length=1, max_length=128)


class GenerationAccepted(BaseModel):
    id: UUID
    status: Literal["queued"]


class GenerationJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_id: UUID


class GenerationListItem(BaseModel):
    id: UUID
    status: GenerationStatus
    project_id: UUID
    project_name: str
    project_slug: str
    inference_endpoint_id: UUID
    inference_endpoint_name: str
    vast_endpoint_name: str
    created_at: datetime
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    completed_at: datetime | None
    queue_ms: int | None
    generation_ms: int | None
    total_ms: int | None


class GenerationPage(BaseModel):
    items: list[GenerationListItem]
    next_before: datetime | None = None


class GenerationDetail(BaseModel):
    id: UUID
    status: GenerationStatus
    project_id: UUID
    project_name: str
    project_slug: str
    inference_endpoint_id: UUID
    inference_endpoint_name: str
    vast_endpoint_name: str
    created_at: datetime
    finished_at: datetime | None
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    updated_at: datetime
    queue_ms: int | None
    preprocess_ms: int | None
    generation_ms: int | None
    postprocess_ms: int | None
    total_ms: int | None
    vast_latency_ms: int | None
    attempts: int
    qstash_message_id: str | None
    workflow_json: dict[str, Any]
    webhook_extra_params: dict[str, Any]
    webhook_url: str | None
    webhook_url_override: str | None
    outputs: list[Any] | None
    sanitized_provider_request: dict[str, Any] | None
    raw_provider_response: dict[str, Any] | None
    webhook_payload: dict[str, Any] | None
    error_message: str | None
    error_details: dict[str, Any] | None
