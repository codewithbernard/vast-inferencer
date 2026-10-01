from typing import Any

from vast_inferencer.config import get_settings

REDACTED = "[REDACTED]"
_SECRET_KEYS = {
    "access_key_id",
    "secret_access_key",
    "secret",
    "authorization",
    "api_key",
    "token",
    "password",
}


def redact(value: Any) -> Any:
    try:
        secrets = [item for item in get_settings().secret_values() if len(item) >= 8]
    except Exception:
        secrets = []
    return _redact(value, secrets)


def _redact(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in _SECRET_KEYS:
                redacted[key] = REDACTED
            else:
                redacted[key] = _redact(item, secrets)
        return redacted
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        return _redact_text(value, secrets)
    return value


def _redact_text(value: str, secrets: list[str]) -> str:
    redacted = value
    for secret in sorted(secrets, key=len, reverse=True):
        if secret in redacted:
            redacted = redacted.replace(secret, REDACTED)
    return redacted
