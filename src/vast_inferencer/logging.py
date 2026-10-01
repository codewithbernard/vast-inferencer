import logging

from vast_inferencer.config import get_settings

_LOGGER_NAME = "vast_inferencer"
_SAFE_FIELDS = {"request_id", "project_id", "status_code", "route", "error_type"}
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
        redacted = redacted.replace(secret, "[redacted]")
    return redacted
