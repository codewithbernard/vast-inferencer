from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import AnyHttpUrl, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_remembered_secrets: set[str] = set()


def remember_secret(value: str) -> None:
    if len(value) >= 8:
        _remembered_secrets.add(value)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    vast_api_key: SecretStr
    qstash_url: AnyHttpUrl
    qstash_token: SecretStr
    qstash_current_signing_key: SecretStr
    qstash_next_signing_key: SecretStr
    public_app_url: AnyHttpUrl
    api_bearer_key: SecretStr
    database_url: SecretStr
    secrets_encryption_key: SecretStr
    log_level: str = "INFO"

    @field_validator("qstash_url", "public_app_url", mode="before")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return str(value).strip().rstrip("/")

    @field_validator("database_url", "secrets_encryption_key", mode="before")
    @classmethod
    def strip_secret(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("secrets_encryption_key")
    @classmethod
    def encryption_key_must_be_fernet(cls, value: SecretStr) -> SecretStr:
        try:
            Fernet(value.get_secret_value().encode())
        except Exception:
            raise ValueError("must be a url-safe Fernet key") from None
        return value

    @property
    def public_base_url(self) -> str:
        return str(self.public_app_url).rstrip("/")

    @property
    def qstash_base_url(self) -> str:
        return str(self.qstash_url).rstrip("/")

    @property
    def internal_generation_url(self) -> str:
        return f"{self.public_base_url}/internal/generations"

    @property
    def comfyui_webhook_url(self) -> str:
        return f"{self.public_base_url}/webhooks/comfyui"

    def secret_values(self) -> list[str]:
        values = [
            self.vast_api_key.get_secret_value(),
            self.qstash_token.get_secret_value(),
            self.qstash_current_signing_key.get_secret_value(),
            self.qstash_next_signing_key.get_secret_value(),
            self.api_bearer_key.get_secret_value(),
            self.database_url.get_secret_value(),
            self.secrets_encryption_key.get_secret_value(),
            *_remembered_secrets,
        ]
        return [value for value in values if value]


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        messages: list[str] = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            message = str(error.get("msg", "invalid configuration"))
            messages.append(f"{location}: {message}" if location else message)
        detail = "; ".join(messages) if messages else "invalid configuration"
        raise RuntimeError(f"Invalid environment configuration ({detail})") from None
