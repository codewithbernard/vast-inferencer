import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from vast_inferencer.auth import require_api_key
from vast_inferencer.logging import log_event
from vast_inferencer.models import GenerationAccepted, GenerationJob, GenerationRequest
from vast_inferencer.registry import ProjectConfigError, UnknownProjectError
from vast_inferencer.services.projects import get_project
from vast_inferencer.services.qstash import PublishError, publish_generation

router = APIRouter()


@router.post("/v1/generations", status_code=202)
async def create_generation(
    body: GenerationRequest,
    _: Annotated[None, Depends(require_api_key)],
) -> GenerationAccepted:
    try:
        get_project(body.project_id)
    except UnknownProjectError:
        raise HTTPException(status_code=404, detail="Unknown project") from None
    except ProjectConfigError as exc:
        log_event(
            logging.ERROR,
            "project_config_missing",
            project_id=body.project_id,
            error_type=exc.env_name,
        )
        raise HTTPException(status_code=500, detail="Project is not configured") from None

    request_id = str(uuid.uuid4())
    job = GenerationJob(
        request_id=request_id,
        project_id=body.project_id,
        workflow_json=body.workflow_json,
        webhook_extra_params=body.webhook_extra_params,
    )
    try:
        publish_generation(job)
    except PublishError as exc:
        log_event(
            logging.ERROR,
            "generation_publish_failed",
            request_id=request_id,
            project_id=body.project_id,
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="Failed to queue generation") from None

    log_event(
        logging.INFO,
        "generation_accepted",
        request_id=request_id,
        project_id=body.project_id,
        route="/v1/generations",
    )
    return GenerationAccepted(request_id=request_id, status="in_progress")
