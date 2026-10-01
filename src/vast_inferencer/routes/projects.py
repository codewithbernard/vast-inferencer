from uuid import UUID

from fastapi import APIRouter, Depends

from vast_inferencer.auth import require_api_key
from vast_inferencer.errors import ConflictError, NotFoundError
from vast_inferencer.http import raise_mapped
from vast_inferencer.models import ProjectCreate, ProjectDetail, ProjectOut, ProjectUpdate
from vast_inferencer.services.records import (
    create_project,
    get_project,
    list_projects,
    update_project,
)

router = APIRouter(prefix="/v1/projects", dependencies=[Depends(require_api_key)])


@router.get("")
async def list_project_records() -> list[ProjectOut]:
    return await list_projects()


@router.post("", status_code=201)
async def create_project_record(body: ProjectCreate) -> ProjectOut:
    try:
        return await create_project(body)
    except (NotFoundError, ConflictError) as exc:
        raise_mapped(exc)


@router.get("/{project_id}")
async def read_project(project_id: UUID) -> ProjectDetail:
    try:
        return await get_project(project_id)
    except NotFoundError as exc:
        raise_mapped(exc)


@router.patch("/{project_id}")
async def patch_project(project_id: UUID, body: ProjectUpdate) -> ProjectOut:
    try:
        return await update_project(project_id, body)
    except (NotFoundError, ConflictError) as exc:
        raise_mapped(exc)
