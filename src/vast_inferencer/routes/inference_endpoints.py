from uuid import UUID

from fastapi import APIRouter, Depends

from vast_inferencer.auth import require_api_key
from vast_inferencer.errors import ConflictError, NotFoundError
from vast_inferencer.http import raise_mapped
from vast_inferencer.models import (
    InferenceEndpointCreate,
    InferenceEndpointDetail,
    InferenceEndpointOut,
    InferenceEndpointUpdate,
)
from vast_inferencer.services.records import (
    create_endpoint,
    get_endpoint,
    list_endpoints,
    update_endpoint,
)

router = APIRouter(prefix="/v1/inference-endpoints", dependencies=[Depends(require_api_key)])


@router.get("")
async def list_inference_endpoints() -> list[InferenceEndpointOut]:
    return await list_endpoints()


@router.post("", status_code=201)
async def create_inference_endpoint(body: InferenceEndpointCreate) -> InferenceEndpointOut:
    try:
        return await create_endpoint(body)
    except ConflictError as exc:
        raise_mapped(exc)


@router.get("/{endpoint_id}")
async def read_inference_endpoint(endpoint_id: UUID) -> InferenceEndpointDetail:
    try:
        return await get_endpoint(endpoint_id)
    except NotFoundError as exc:
        raise_mapped(exc)


@router.patch("/{endpoint_id}")
async def patch_inference_endpoint(
    endpoint_id: UUID,
    body: InferenceEndpointUpdate,
) -> InferenceEndpointOut:
    try:
        return await update_endpoint(endpoint_id, body)
    except (NotFoundError, ConflictError) as exc:
        raise_mapped(exc)
