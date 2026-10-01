from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from vast_inferencer.auth import require_api_key
from vast_inferencer.db import session_scope
from vast_inferencer.errors import ConflictError, NotFoundError, PublishFailedError
from vast_inferencer.http import raise_mapped
from vast_inferencer.models import (
    GenerationAccepted,
    GenerationCreate,
    GenerationCreateCompat,
    GenerationDetail,
    GenerationPage,
    GenerationStatus,
)
from vast_inferencer.services.generations import create_generation, get_generation, list_generations
from vast_inferencer.tables import Project

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get("/v1/generations")
async def list_all_generations(
    status: Annotated[GenerationStatus | None, Query()] = None,
    before: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GenerationPage:
    async with session_scope() as session:
        return await list_generations(session, status=status, before=before, limit=limit)


@router.get("/v1/projects/{project_id}/generations")
async def list_project_generations(
    project_id: UUID,
    status: Annotated[GenerationStatus | None, Query()] = None,
    before: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GenerationPage:
    try:
        async with session_scope() as session:
            if await session.get(Project, project_id) is None:
                raise NotFoundError("Project not found")
            return await list_generations(
                session,
                project_id=project_id,
                status=status,
                before=before,
                limit=limit,
            )
    except NotFoundError as exc:
        raise_mapped(exc)


@router.post("/v1/projects/{project_id}/generations", status_code=202)
async def create_project_generation(
    project_id: UUID,
    body: GenerationCreate,
) -> GenerationAccepted:
    return await _accept(
        project_id=project_id,
        slug=None,
        body=body,
    )


@router.post("/v1/generations", status_code=202)
async def create_generation_for_slug(body: GenerationCreateCompat) -> GenerationAccepted:
    return await _accept(
        project_id=None,
        slug=body.project_id,
        body=body,
    )


@router.get("/v1/generations/{generation_id}")
async def read_generation(generation_id: UUID) -> GenerationDetail:
    try:
        async with session_scope() as session:
            return await get_generation(session, generation_id)
    except NotFoundError as exc:
        raise_mapped(exc)


async def _accept(
    *,
    project_id: UUID | None,
    slug: str | None,
    body: GenerationCreate,
) -> GenerationAccepted:
    try:
        generation = await create_generation(
            project_id=project_id,
            slug=slug,
            workflow_json=body.workflow_json,
            webhook_extra_params=body.webhook_extra_params,
            webhook_url=None if body.webhook_url is None else str(body.webhook_url),
        )
    except (NotFoundError, ConflictError, PublishFailedError) as exc:
        raise_mapped(exc)
    return GenerationAccepted(id=generation.id, status="queued")
