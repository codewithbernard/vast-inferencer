from typing import Any

from vastai import Serverless

from vast_inferencer.config import get_settings
from vast_inferencer.limits import (
    VAST_MAX_RETRIES,
    VAST_REQUEST_COST,
    VAST_REQUEST_TIMEOUT_SECONDS,
    VAST_WORKER_TIMEOUT_SECONDS,
)
from vast_inferencer.models import GenerationJob
from vast_inferencer.registry import ProjectConfig
from vast_inferencer.services.projects import get_project

GENERATE_SYNC_ROUTE = "/generate/sync"

class VastTransportError(Exception):
    def __init__(self, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__("Vast request failed")


def build_vast_payload(project: ProjectConfig, job: GenerationJob) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "input": {
            "request_id": job.request_id,
            "workflow_json": job.workflow_json,
            "s3": {
                "access_key_id": project.s3.access_key_id.get_secret_value(),
                "secret_access_key": project.s3.secret_access_key.get_secret_value(),
                "endpoint_url": project.s3.endpoint_url,
                "bucket_name": project.s3.bucket_name,
                "region": project.s3.region,
            },
        }
    }
    if project.webhook is not None:
        extra_params = {**project.webhook.extra_params, **job.webhook_extra_params}
        extra_params["request_id"] = job.request_id
        webhook: dict[str, Any] = {
            "url": str(project.webhook.url),
            "extra_params": extra_params,
        }
        if project.webhook.secret is not None:
            webhook["secret"] = project.webhook.secret.get_secret_value()
        payload["input"]["webhook"] = webhook
    return payload


async def run_generation_job(job: GenerationJob) -> None:
    settings = get_settings()
    project = get_project(job.project_id)
    payload = build_vast_payload(project, job)
    async with Serverless(api_key=settings.vast_api_key.get_secret_value()) as client:
        endpoint = await client.get_endpoint(name=project.endpoint_name)
        # endpoint.request() cannot set worker_timeout, so call the queue API directly.
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
    if not isinstance(result, dict) or not result.get("ok"):
        status_code = result.get("status") if isinstance(result, dict) else None
        raise VastTransportError(status_code if isinstance(status_code, int) else None)
