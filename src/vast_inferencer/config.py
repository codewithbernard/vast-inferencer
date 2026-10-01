from functools import lru_cache

from pydantic import AnyHttpUrl, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from vast_inferencer.registry import configured_secret_values


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
    log_level: str = "INFO"

    @field_validator("qstash_url", "public_app_url", mode="before")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return str(value).strip().rstrip("/")

    @property
    def public_base_url(self) -> str:
        return str(self.public_app_url).rstrip("/")

    @property
    def qstash_base_url(self) -> str:
        return str(self.qstash_url).rstrip("/")

    @property
    def internal_generation_url(self) -> str:
        return f"{self.public_base_url}/internal/generations"

    def secret_values(self) -> list[str]:
        values = [
            self.vast_api_key.get_secret_value(),
            self.qstash_token.get_secret_value(),
            self.qstash_current_signing_key.get_secret_value(),
            self.qstash_next_signing_key.get_secret_value(),
            self.api_bearer_key.get_secret_value(),
            *configured_secret_values(),
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
