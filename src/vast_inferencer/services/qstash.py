import json
from typing import Any
from uuid import UUID

from qstash import QStash, Receiver
from qstash.errors import SignatureError

from vast_inferencer.config import get_settings
from vast_inferencer.limits import (
    QSTASH_FLOW_CONTROL_KEY,
    QSTASH_FLOW_CONTROL_PARALLELISM,
    QSTASH_FORWARD_FLOW_CONTROL_KEY,
    QSTASH_FORWARD_FLOW_CONTROL_PARALLELISM,
    QSTASH_FORWARD_RETRIES,
    QSTASH_FORWARD_TIMEOUT,
    QSTASH_RETRIES,
    QSTASH_RETRY_DELAY,
    QSTASH_TIMEOUT,
)


class PublishError(Exception):
    pass


def publish_generation(generation_id: UUID) -> str:
    settings = get_settings()
    body = {"generation_id": str(generation_id)}
    _reject_secrets(body)
    client = _client()
    try:
        response = client.message.publish_json(
            url=settings.internal_generation_url,
            body=body,
            deduplication_id=str(generation_id),
            retries=QSTASH_RETRIES,
            retry_delay=QSTASH_RETRY_DELAY,
            timeout=QSTASH_TIMEOUT,
            flow_control={
                "key": QSTASH_FLOW_CONTROL_KEY,
                "parallelism": QSTASH_FLOW_CONTROL_PARALLELISM,
            },
            redact={"body": True},
        )
    except Exception as exc:
        raise PublishError(type(exc).__name__) from None
    message_id = getattr(response, "message_id", None)
    if not isinstance(message_id, str) or not message_id:
        raise PublishError("UnexpectedPublishResponse")
    return message_id


def publish_forward(
    *,
    url: str,
    body: str,
    signature: str,
    deduplication_id: str,
) -> None:
    _reject_secret_text(body)
    client = _client()
    try:
        client.message.publish(
            url=url,
            body=body,
            content_type="application/json",
            headers={"X-Webhook-Signature": signature},
            deduplication_id=deduplication_id,
            retries=QSTASH_FORWARD_RETRIES,
            timeout=QSTASH_FORWARD_TIMEOUT,
            flow_control={
                "key": QSTASH_FORWARD_FLOW_CONTROL_KEY,
                "parallelism": QSTASH_FORWARD_FLOW_CONTROL_PARALLELISM,
            },
            redact={"body": True, "header": ["X-Webhook-Signature"]},
        )
    except Exception as exc:
        raise PublishError(type(exc).__name__) from None


def verify_delivery(*, body: str, signature: str | None) -> None:
    if not signature:
        raise SignatureError("Missing signature")
    settings = get_settings()
    receiver = Receiver(
        current_signing_key=settings.qstash_current_signing_key.get_secret_value(),
        next_signing_key=settings.qstash_next_signing_key.get_secret_value(),
    )
    receiver.verify(
        signature=signature,
        body=body,
        url=settings.internal_generation_url,
    )


def _client() -> QStash:
    settings = get_settings()
    return QStash(
        settings.qstash_token.get_secret_value(),
        base_url=settings.qstash_base_url,
    )


def _reject_secrets(body: dict[str, Any]) -> None:
    _reject_secret_text(json.dumps(body))


def _reject_secret_text(encoded: str) -> None:
    for secret in get_settings().secret_values():
        if len(secret) >= 8 and secret in encoded:
            raise PublishError("SecretInMessage")
