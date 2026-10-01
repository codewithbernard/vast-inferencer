import json
from typing import Any

from qstash import QStash, Receiver
from qstash.errors import SignatureError

from vast_inferencer.config import get_settings
from vast_inferencer.limits import (
    QSTASH_FLOW_CONTROL_KEY,
    QSTASH_FLOW_CONTROL_PARALLELISM,
    QSTASH_RETRIES,
    QSTASH_RETRY_DELAY,
    QSTASH_TIMEOUT,
)
from vast_inferencer.models import GenerationJob


class PublishError(Exception):
    pass


def publish_generation(job: GenerationJob) -> str:
    settings = get_settings()
    body = job.model_dump(mode="json")
    _reject_secrets(body)
    client = QStash(
        settings.qstash_token.get_secret_value(),
        base_url=settings.qstash_base_url,
    )
    try:
        response = client.message.publish_json(
            url=settings.internal_generation_url,
            body=body,
            deduplication_id=job.request_id,
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


def _reject_secrets(body: dict[str, Any]) -> None:
    encoded = json.dumps(body)
    for secret in get_settings().secret_values():
        if secret and secret in encoded:
            raise PublishError("SecretInMessage")
