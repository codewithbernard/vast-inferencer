from typing import Any

from vastai import Serverless

from vast_inferencer.config import get_settings
from vast_inferencer.limits import (
    VAST_MAX_RETRIES,
    VAST_REQUEST_COST,
    VAST_REQUEST_TIMEOUT_SECONDS,
    VAST_WORKER_TIMEOUT_SECONDS,
)

GENERATE_SYNC_ROUTE = "/generate/sync"
_DROPPED_RESULT_KEYS = {"auth_data"}


class VastTransportError(Exception):
    def __init__(self, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__("Vast request failed")


def build_vast_payload(
    *,
    generation_id: str,
    project_id: str,
    workflow_json: dict[str, Any],
    webhook_extra_params: dict[str, Any],
    s3_access_key_id: str,
    s3_secret_access_key: str,
    s3_endpoint_url: str,
    s3_bucket_name: str,
    s3_region: str,
    webhook_secret: str,
) -> dict[str, Any]:
    extra_params = dict(webhook_extra_params)
    extra_params["project_id"] = project_id
    extra_params["generation_id"] = generation_id
    return {
        "input": {
            "request_id": generation_id,
            "workflow_json": workflow_json,
            "s3": {
                "access_key_id": s3_access_key_id,
                "secret_access_key": s3_secret_access_key,
                "endpoint_url": s3_endpoint_url,
                "bucket_name": s3_bucket_name,
                "region": s3_region,
            },
            "webhook": {
                "url": get_settings().comfyui_webhook_url,
                "secret": webhook_secret,
                "extra_params": extra_params,
            },
        }
    }


async def call_generate_sync(endpoint_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    async with Serverless(api_key=settings.vast_api_key.get_secret_value()) as client:
        endpoint = await client.get_endpoint(name=endpoint_name)
        request = client.queue_endpoint_request(
            endpoint=endpoint,
            worker_route=GENERATE_SYNC_ROUTE,
            worker_payload=payload,
            cost=VAST_REQUEST_COST,
            timeout=VAST_REQUEST_TIMEOUT_SECONDS,
            worker_timeout=VAST_WORKER_TIMEOUT_SECONDS,
            retry=True,
            max_retries=VAST_MAX_RETRIES,
        )
        result = await request
    if not isinstance(result, dict):
        raise VastTransportError()
    return _public_result(result)


def _public_result(result: dict[str, Any]) -> dict[str, Any]:
    url = result.get("url")
    if isinstance(url, str) and "?" in url:
        url = url.split("?", 1)[0]
    stored: dict[str, Any] = {
        "response": result.get("response"),
        "ok": result.get("ok"),
        "status": result.get("status"),
        "latency": result.get("latency"),
        "url": url,
        "request_idx": result.get("request_idx"),
    }
    if not isinstance(result.get("response"), dict):
        text = result.get("text")
        if isinstance(text, str):
            stored["text"] = text[:4000]
    for key in _DROPPED_RESULT_KEYS:
        stored.pop(key, None)
    return stored
