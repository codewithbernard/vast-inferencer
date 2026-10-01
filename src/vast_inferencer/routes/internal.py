import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from qstash.errors import SignatureError

from vast_inferencer.logging import log_event
from vast_inferencer.models import GenerationJob
from vast_inferencer.registry import ProjectConfigError, UnknownProjectError
from vast_inferencer.services.qstash import verify_delivery
from vast_inferencer.services.vast import VastTransportError, run_generation_job

router = APIRouter()


@router.post("/internal/generations")
async def consume_generation(request: Request) -> JSONResponse:
    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        return _non_retryable("Invalid body")

    try:
        verify_delivery(body=body, signature=request.headers.get("upstash-signature"))
    except SignatureError:
        return _non_retryable("Invalid signature")

    try:
        job = GenerationJob.model_validate_json(body)
    except ValidationError:
        return _non_retryable("Invalid generation job")

    try:
        await run_generation_job(job)
    except UnknownProjectError:
        return _non_retryable("Unknown project")
    except ProjectConfigError as exc:
        log_event(
            logging.ERROR,
            "project_config_missing",
            request_id=job.request_id,
            project_id=job.project_id,
            error_type=exc.env_name,
        )
        return _non_retryable("Project is not configured")
    except VastTransportError as exc:
        log_event(
            logging.ERROR,
            "generation_transport_failed",
            request_id=job.request_id,
            project_id=job.project_id,
            status_code=exc.status_code,
            error_type=type(exc).__name__,
        )
        return JSONResponse(status_code=502, content={"detail": "Generation failed"})
    except Exception as exc:
        log_event(
            logging.ERROR,
            "generation_failed",
            request_id=job.request_id,
            project_id=job.project_id,
            error_type=type(exc).__name__,
        )
        return JSONResponse(status_code=502, content={"detail": "Generation failed"})

    log_event(
        logging.INFO,
        "generation_submitted",
        request_id=job.request_id,
        project_id=job.project_id,
        route="/internal/generations",
    )
    return JSONResponse(status_code=200, content={"ok": True})


def _non_retryable(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=489,
        content={"detail": detail},
        headers={"Upstash-NonRetryable-Error": "true"},
    )
