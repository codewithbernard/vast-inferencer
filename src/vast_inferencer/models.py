import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=128)
    workflow_json: dict[str, Any] = Field(min_length=1)
    webhook_extra_params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("workflow_json", "webhook_extra_params")
    @classmethod
    def values_must_be_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        json.dumps(value)
        return value


class GenerationJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_json: dict[str, Any] = Field(min_length=1)
    webhook_extra_params: dict[str, Any] = Field(default_factory=dict)


class GenerationAccepted(BaseModel):
    request_id: str
    status: Literal["in_progress"]
