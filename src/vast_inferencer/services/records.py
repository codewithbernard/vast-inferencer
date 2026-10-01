import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vast_inferencer.crypto import encrypt_secret
from vast_inferencer.db import session_scope
from vast_inferencer.errors import ConflictError, NotFoundError
from vast_inferencer.models import (
    InferenceEndpointCreate,
    InferenceEndpointDetail,
    InferenceEndpointOut,
    InferenceEndpointUpdate,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    ProjectUpdate,
)
from vast_inferencer.present import endpoint_out, project_out
from vast_inferencer.services.generations import list_generations
from vast_inferencer.tables import InferenceEndpoint, Project


async def list_endpoints() -> list[InferenceEndpointOut]:
    async with session_scope() as session:
        endpoints = list(
            await session.scalars(
                select(InferenceEndpoint).order_by(InferenceEndpoint.created_at.desc())
            )
        )
        counts = await _project_counts(session)
        return [endpoint_out(endpoint, counts.get(endpoint.id, 0)) for endpoint in endpoints]


async def create_endpoint(body: InferenceEndpointCreate) -> InferenceEndpointOut:
    now = datetime.now(UTC)
    async with session_scope() as session:
        await _ensure_endpoint_name_available(session, body.vast_endpoint_name, None)
        endpoint = InferenceEndpoint(
            id=uuid4(),
            name=body.name,
            vast_endpoint_name=body.vast_endpoint_name,
            enabled=body.enabled,
            created_at=now,
            updated_at=now,
        )
        session.add(endpoint)
        await _flush_unique(session, "An inference endpoint with that Vast name already exists")
        return endpoint_out(endpoint, 0)


async def get_endpoint(endpoint_id: UUID) -> InferenceEndpointDetail:
    async with session_scope() as session:
        endpoint = await session.get(InferenceEndpoint, endpoint_id)
        if endpoint is None:
            raise NotFoundError("Inference endpoint not found")
        projects = list(
            await session.scalars(
                select(Project)
                .where(Project.inference_endpoint_id == endpoint.id)
                .order_by(Project.created_at.desc())
            )
        )
        page = await list_generations(session, endpoint_id=endpoint.id, limit=20)
        count = len(projects)
        return InferenceEndpointDetail(
            **endpoint_out(endpoint, count).model_dump(),
            projects=[project_out(project, endpoint) for project in projects],
            recent_generations=page.items,
        )


async def update_endpoint(
    endpoint_id: UUID,
    body: InferenceEndpointUpdate,
) -> InferenceEndpointOut:
    async with session_scope() as session:
        endpoint = await session.get(InferenceEndpoint, endpoint_id)
        if endpoint is None:
            raise NotFoundError("Inference endpoint not found")
        fields = body.model_fields_set
        if "name" in fields and body.name is not None:
            endpoint.name = body.name
        if "vast_endpoint_name" in fields and body.vast_endpoint_name is not None:
            await _ensure_endpoint_name_available(session, body.vast_endpoint_name, endpoint.id)
            endpoint.vast_endpoint_name = body.vast_endpoint_name
        if "enabled" in fields and body.enabled is not None:
            endpoint.enabled = body.enabled
        endpoint.updated_at = datetime.now(UTC)
        await _flush_unique(session, "An inference endpoint with that Vast name already exists")
        count = await session.scalar(
            select(func.count())
            .select_from(Project)
            .where(Project.inference_endpoint_id == endpoint.id)
        )
        return endpoint_out(endpoint, int(count or 0))


async def list_projects() -> list[ProjectOut]:
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Project, InferenceEndpoint)
                .join(InferenceEndpoint, InferenceEndpoint.id == Project.inference_endpoint_id)
                .order_by(Project.created_at.desc())
            )
        ).all()
        return [project_out(project, endpoint) for project, endpoint in rows]


async def create_project(body: ProjectCreate) -> ProjectOut:
    now = datetime.now(UTC)
    webhook_secret = _secret_or_generated(body.webhook_secret)
    async with session_scope() as session:
        endpoint = await session.get(InferenceEndpoint, body.inference_endpoint_id)
        if endpoint is None:
            raise NotFoundError("Inference endpoint not found")
        await _ensure_slug_available(session, body.slug, None)
        project = Project(
            id=uuid4(),
            name=body.name,
            slug=body.slug,
            inference_endpoint_id=endpoint.id,
            s3_endpoint_url=body.s3.endpoint_url,
            s3_bucket_name=body.s3.bucket_name,
            s3_region=body.s3.region,
            s3_access_key_id_enc=encrypt_secret(body.s3.access_key_id.get_secret_value().strip()),
            s3_secret_access_key_enc=encrypt_secret(
                body.s3.secret_access_key.get_secret_value().strip()
            ),
            webhook_url=None if body.webhook_url is None else str(body.webhook_url),
            webhook_secret_enc=encrypt_secret(webhook_secret),
            created_at=now,
            updated_at=now,
        )
        session.add(project)
        await _flush_unique(session, "A project with that slug already exists")
        return project_out(project, endpoint)


async def get_project(project_id: UUID) -> ProjectDetail:
    async with session_scope() as session:
        row = (
            await session.execute(
                select(Project, InferenceEndpoint)
                .join(InferenceEndpoint, InferenceEndpoint.id == Project.inference_endpoint_id)
                .where(Project.id == project_id)
            )
        ).first()
        if row is None:
            raise NotFoundError("Project not found")
        project, endpoint = row
        page = await list_generations(session, project_id=project.id, limit=20)
        return ProjectDetail(
            **project_out(project, endpoint).model_dump(),
            recent_generations=page.items,
        )


async def update_project(project_id: UUID, body: ProjectUpdate) -> ProjectOut:
    async with session_scope() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        fields = body.model_fields_set
        if "inference_endpoint_id" in fields and body.inference_endpoint_id is not None:
            endpoint = await session.get(InferenceEndpoint, body.inference_endpoint_id)
            if endpoint is None:
                raise NotFoundError("Inference endpoint not found")
            project.inference_endpoint_id = endpoint.id
        else:
            endpoint = await session.get(InferenceEndpoint, project.inference_endpoint_id)
            if endpoint is None:
                raise NotFoundError("Inference endpoint not found")
        if "name" in fields and body.name is not None:
            project.name = body.name
        if "slug" in fields and body.slug is not None:
            await _ensure_slug_available(session, body.slug, project.id)
            project.slug = body.slug
        if "s3_endpoint_url" in fields and body.s3_endpoint_url is not None:
            project.s3_endpoint_url = body.s3_endpoint_url
        if "s3_bucket_name" in fields and body.s3_bucket_name is not None:
            project.s3_bucket_name = body.s3_bucket_name
        if "s3_region" in fields and body.s3_region is not None:
            project.s3_region = body.s3_region
        if "s3_access_key_id" in fields and body.s3_access_key_id is not None:
            project.s3_access_key_id_enc = encrypt_secret(
                body.s3_access_key_id.get_secret_value().strip()
            )
        if "s3_secret_access_key" in fields and body.s3_secret_access_key is not None:
            project.s3_secret_access_key_enc = encrypt_secret(
                body.s3_secret_access_key.get_secret_value().strip()
            )
        if "webhook_url" in fields:
            project.webhook_url = None if body.webhook_url is None else str(body.webhook_url)
        if "webhook_secret" in fields and body.webhook_secret is not None:
            secret = body.webhook_secret.get_secret_value().strip()
            project.webhook_secret_enc = encrypt_secret(secret)
        project.updated_at = datetime.now(UTC)
        await _flush_unique(session, "A project with that slug already exists")
        return project_out(project, endpoint)


async def list_project_slugs() -> list[str]:
    async with session_scope() as session:
        rows = await session.scalars(select(Project.slug).order_by(Project.slug))
        return list(rows)


async def _project_counts(session: AsyncSession) -> dict[UUID, int]:
    rows = (
        await session.execute(
            select(Project.inference_endpoint_id, func.count()).group_by(
                Project.inference_endpoint_id
            )
        )
    ).all()
    return {endpoint_id: int(count) for endpoint_id, count in rows}


async def _ensure_endpoint_name_available(
    session: AsyncSession,
    name: str,
    current_id: UUID | None,
) -> None:
    stmt = select(InferenceEndpoint.id).where(InferenceEndpoint.vast_endpoint_name == name)
    if current_id is not None:
        stmt = stmt.where(InferenceEndpoint.id != current_id)
    if await session.scalar(stmt) is not None:
        raise ConflictError("An inference endpoint with that Vast name already exists")


async def _ensure_slug_available(
    session: AsyncSession,
    slug: str,
    current_id: UUID | None,
) -> None:
    stmt = select(Project.id).where(Project.slug == slug)
    if current_id is not None:
        stmt = stmt.where(Project.id != current_id)
    if await session.scalar(stmt) is not None:
        raise ConflictError("A project with that slug already exists")


async def _flush_unique(session: AsyncSession, message: str) -> None:
    try:
        await session.flush()
    except IntegrityError:
        raise ConflictError(message) from None


def _secret_or_generated(value: object) -> str:
    from pydantic import SecretStr

    if isinstance(value, SecretStr):
        text = value.get_secret_value().strip()
        if text:
            return text
    return secrets.token_urlsafe(32)
