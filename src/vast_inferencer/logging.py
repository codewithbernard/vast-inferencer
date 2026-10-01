import logging

from vast_inferencer.config import get_settings
from vast_inferencer.sanitize import REDACTED

_LOGGER_NAME = "vast_inferencer"
_SAFE_FIELDS = {
    "request_id",
    "generation_id",
    "project_id",
    "inference_endpoint_id",
    "vast_endpoint_name",
    "status_code",
    "route",
    "error_type",
    "from_status",
    "to_status",
    "queued_at",
    "started_at",
    "completed_at",
    "queue_ms",
    "generation_ms",
    "total_ms",
    "source",
    "error_message",
}
_REDACTING = False


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        global _REDACTING
        if _REDACTING:
            return True
        _REDACTING = True
        try:
            message = _redact(record.getMessage())
        except Exception:
            return True
        finally:
            _REDACTING = False
        record.msg = message
        record.args = ()
        return True


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level)
    root = logging.getLogger()
    root.setLevel(level)
    _attach_filter(root)
    for name in ("vastai", "Serverless", "uvicorn", "uvicorn.error", _LOGGER_NAME):
        _attach_filter(logging.getLogger(name))


def log_event(level: int, event: str, **fields: object) -> None:
    safe = {key: fields[key] for key in _SAFE_FIELDS if key in fields}
    logging.getLogger(_LOGGER_NAME).log(level, "%s %s", event, safe)


def log_transition(*, failed: bool, **fields: object) -> None:
    message = fields.get("error_message")
    if isinstance(message, str):
        fields["error_message"] = message[:300]
    log_event(logging.ERROR if failed else logging.INFO, "generation_transition", **fields)


def _attach_filter(logger: logging.Logger) -> None:
    if not any(isinstance(item, RedactingFilter) for item in logger.filters):
        logger.addFilter(RedactingFilter())
    for handler in logger.handlers:
        if not any(isinstance(item, RedactingFilter) for item in handler.filters):
            handler.addFilter(RedactingFilter())


def _redact(message: str) -> str:
    try:
        secrets = get_settings().secret_values()
    except Exception:
        return message
    redacted = message
    for secret in sorted(secrets, key=len, reverse=True):
        if len(secret) >= 8:
            redacted = redacted.replace(secret, REDACTED)
    return redacted
