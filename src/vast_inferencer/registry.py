import os
from dataclasses import dataclass, field
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, ValidationError


class UnknownProjectError(Exception):
    pass


class ProjectConfigError(Exception):
    def __init__(self, project_id: str, env_name: str) -> None:
        self.project_id = project_id
        self.env_name = env_name
        super().__init__(f"{project_id} is missing {env_name}")


class S3Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_key_id: SecretStr
    secret_access_key: SecretStr
    endpoint_url: str = Field(min_length=1)
    bucket_name: str = Field(min_length=1)
    region: str = ""


class WebhookConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: AnyHttpUrl
    extra_params: dict[str, Any] = Field(default_factory=dict)
    secret: SecretStr | None = None


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    endpoint_name: str
    s3: S3Config
    webhook: WebhookConfig | None = None


@dataclass(frozen=True)
class ProjectSpec:
    project_id: str
    endpoint_name: str
    s3_endpoint_url: str
    s3_bucket_name: str
    s3_region: str
    s3_access_key_id: str
    s3_secret_access_key_env: str
    webhook_url: str | None = None
    webhook_extra_params: dict[str, Any] = field(default_factory=dict)
    webhook_secret_env: str | None = None


# Add a project here. Its Vast endpoint name stays in this file.
# The storage password is read from the named env var.
PROJECTS: dict[str, ProjectSpec] = {
    "ai-ofm-studio": ProjectSpec(
        project_id="ai-ofm-studio",
        endpoint_name="minimax-h3",
        s3_endpoint_url="https://de-s3.storage.bunnycdn.com",
        s3_bucket_name="ai-ofm-studio",
        s3_region="de",
        s3_access_key_id="ai-ofm-studio",
        s3_secret_access_key_env="AI_OFM_STUDIO_STORAGE_PASSWORD",
    )
}


def resolve_project(project_id: str) -> ProjectConfig:
    spec = PROJECTS.get(project_id)
    if spec is None:
        raise UnknownProjectError(project_id)
    webhook_secret = _optional_env(spec.webhook_secret_env)
    webhook = None
    if spec.webhook_url is not None:
        webhook = {
            "url": spec.webhook_url,
            "extra_params": dict(spec.webhook_extra_params),
            "secret": None if webhook_secret is None else webhook_secret.get_secret_value(),
        }
    try:
        return ProjectConfig.model_validate(
            {
                "project_id": spec.project_id,
                "endpoint_name": spec.endpoint_name,
                "s3": {
                    "access_key_id": spec.s3_access_key_id,
                    "secret_access_key": _required_env(spec, spec.s3_secret_access_key_env),
                    "endpoint_url": spec.s3_endpoint_url,
                    "bucket_name": spec.s3_bucket_name,
                    "region": spec.s3_region,
                },
                "webhook": webhook,
            }
        )
    except ProjectConfigError:
        raise
    except ValidationError:
        raise ProjectConfigError(spec.project_id, "project settings") from None


def configured_secret_values() -> list[str]:
    values: list[str] = []
    for spec in PROJECTS.values():
        for env_name in (
            spec.s3_secret_access_key_env,
            spec.webhook_secret_env,
        ):
            if env_name is None:
                continue
            value = os.environ.get(env_name, "").strip()
            if value:
                values.append(value)
    return values


def _required_env(spec: ProjectSpec, env_name: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise ProjectConfigError(spec.project_id, env_name)
    return value


def _optional_env(env_name: str | None) -> SecretStr | None:
    if env_name is None:
        return None
    value = os.environ.get(env_name, "").strip()
    if not value:
        return None
    return SecretStr(value)
