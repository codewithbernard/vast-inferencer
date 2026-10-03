import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx
from sqlalchemy import and_, bindparam, or_, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from vast_inferencer.crypto import decrypt_secret
from vast_inferencer.db import session_scope
from vast_inferencer.errors import ConflictError, NotFoundError, PublishFailedError
from vast_inferencer.limits import (
    STUCK_QUEUED_SECONDS,
    STUCK_RUNNING_SECONDS,
    SWEEP_BATCH_SIZE,
    VERCEL_MAX_DURATION_SECONDS,
)
from vast_inferencer.logging import log_event, log_transition
from vast_inferencer.models import GenerationDetail, GenerationPage, GenerationStatus
from vast_inferencer.present import (
    generation_detail,
    generation_item,
    queue_duration_ms,
    total_duration_ms,
)
from vast_inferencer.sanitize import redact
from vast_inferencer.services.qstash import PublishError, publish_generation
from vast_inferencer.services.vast import VastTransportError, build_vast_payload, call_generate_sync
from vast_inferencer.tables import Generation, InferenceEndpoint, Project

_TERMINAL = {"completed", "failed"}
_WRAPPER_FAILURES = {"failed", "timeout", "cancelled", "error"}
_CLAIM = text(
    """
    UPDATE generations
    SET status = 'running',
        started_at = NOW(),
        attempts = attempts + 1,
        updated_at = NOW()
    WHERE id = :id AND status = 'queued'
    RETURNING id
    """
).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True)))


class WebhookError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass
class RunContext:
    generation_id: UUID
    vast_endpoint_name: str
    payload: dict[str, Any]

    def __repr__(self) -> str:
        return (
            f"RunContext(generation_id={self.generation_id}, "
            f"vast_endpoint_name={self.vast_endpoint_name!r})"
        )


@dataclass
class PreparedRun:
    action: Literal["run", "skipped", "missing", "stale_failed", "config_failed"]
    context: RunContext | None = None


def verify_webhook_signature(body: bytes, header: str | None, secret: str) -> bool:
    if not header or not header.startswith("sha256=") or not secret:
        return False
    received = header.removeprefix("sha256=")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if len(received) != len(expected):
        return False
    return hmac.compare_digest(received, expected)


async def create_generation(
    *,
    project_id: UUID | None,
    slug: str | None,
    vast_endpoint_name: str,
    workflow_json: dict[str, Any],
    webhook_extra_params: dict[str, Any],
    webhook_url: str | None,
) -> Generation:
    now = _now()
    async with session_scope() as session:
        project = await _load_project(session, project_id=project_id, slug=slug)
        endpoint = await session.scalar(
            select(InferenceEndpoint).where(
                InferenceEndpoint.vast_endpoint_name == vast_endpoint_name
            )
        )
        if endpoint is None:
            raise NotFoundError("Inference endpoint not found")
        if not endpoint.enabled:
            raise ConflictError("Inference endpoint is disabled")
        generation = Generation(
            id=uuid4(),
            project_id=project.id,
            inference_endpoint_id=endpoint.id,
            status="queued",
            created_at=now,
            queued_at=now,
            updated_at=now,
            workflow_json=workflow_json,
            webhook_extra_params=webhook_extra_params,
            webhook_url_override=webhook_url,
            attempts=0,
        )
        session.add(generation)
        await session.flush()
        await _log_generation(session, generation, "", "api")
        generation_id = generation.id

    try:
        message_id = publish_generation(generation_id)
    except PublishError:
        async with session_scope() as session:
            await _mark_publish_failed(session, generation_id)
        raise PublishFailedError from None

    try:
        async with session_scope() as session:
            row = await session.get(Generation, generation_id)
            if row is not None and row.status == "queued":
                row.qstash_message_id = message_id
                row.updated_at = _now()
    except Exception as exc:
        log_event(
            logging.ERROR,
            "generation_message_id_failed",
            generation_id=str(generation_id),
            error_type=type(exc).__name__,
        )
    return generation


async def list_generations(
    session: AsyncSession,
    *,
    project_id: UUID | None = None,
    endpoint_id: UUID | None = None,
    status: GenerationStatus | None = None,
    before: datetime | None = None,
    limit: int = 50,
) -> GenerationPage:
    bounded = min(max(limit, 1), 200)
    stmt = (
        select(Generation, Project, InferenceEndpoint)
        .join(Project, Project.id == Generation.project_id)
        .join(InferenceEndpoint, InferenceEndpoint.id == Generation.inference_endpoint_id)
        .order_by(Generation.created_at.desc())
        .limit(bounded + 1)
    )
    if project_id is not None:
        stmt = stmt.where(Generation.project_id == project_id)
    if endpoint_id is not None:
        stmt = stmt.where(Generation.inference_endpoint_id == endpoint_id)
    if status is not None:
        stmt = stmt.where(Generation.status == status)
    if before is not None:
        stmt = stmt.where(Generation.created_at < before)
    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > bounded
    visible = rows[:bounded]
    items = [
        generation_item(generation, project, endpoint)
        for generation, project, endpoint in visible
    ]
    next_before = visible[-1][0].created_at if has_more and visible else None
    return GenerationPage(items=items, next_before=next_before)


async def get_generation(session: AsyncSession, generation_id: UUID) -> GenerationDetail:
    row = (
        await session.execute(
            select(Generation, Project, InferenceEndpoint)
            .join(Project, Project.id == Generation.project_id)
            .join(InferenceEndpoint, InferenceEndpoint.id == Generation.inference_endpoint_id)
            .where(Generation.id == generation_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("Generation not found")
    generation, project, endpoint = row
    return generation_detail(generation, project, endpoint)


async def run_claimed_generation(generation_id: UUID) -> str:
    async with session_scope() as session:
        prepared = await prepare_run(session, generation_id)
    if prepared.action == "missing":
        return "missing"
    if prepared.action == "skipped":
        return "skipped"
    if prepared.action == "stale_failed" or prepared.action == "config_failed":
        await notify_failure(generation_id)
        return "failed"
    context = prepared.context
    if context is None:
        return "skipped"
    try:
        result = await call_generate_sync(context.vast_endpoint_name, context.payload)
    except Exception as exc:
        log_event(
            logging.ERROR,
            "generation_transport_failed",
            generation_id=str(generation_id),
            vast_endpoint_name=context.vast_endpoint_name,
            error_type=type(exc).__name__,
            status_code=exc.status_code if isinstance(exc, VastTransportError) else None,
        )
        async with session_scope() as session:
            failed = await apply_worker_failure(session, generation_id, exc)
        if failed:
            await notify_failure(generation_id)
        return "failed"
    try:
        async with session_scope() as session:
            failed = await apply_vast_result(session, generation_id, result)
    except Exception as exc:
        log_event(
            logging.ERROR,
            "generation_result_persist_failed",
            generation_id=str(generation_id),
            error_type=type(exc).__name__,
        )
        async with session_scope() as session:
            failed = await apply_worker_failure(session, generation_id, exc)
    if failed:
        await notify_failure(generation_id)
    return "done"


async def prepare_run(session: AsyncSession, generation_id: UUID) -> PreparedRun:
    claimed = (await session.execute(_CLAIM, {"id": generation_id})).first()
    session.expire_all()
    if claimed is not None:
        try:
            context = await _build_context(session, generation_id)
        except Exception as exc:
            await apply_worker_failure(session, generation_id, exc)
            return PreparedRun("config_failed")
        generation = await session.get(Generation, generation_id)
        if generation is not None:
            await _log_generation(session, generation, "queued", "worker")
        return PreparedRun("run", context)

    generation = await _lock(session, generation_id)
    if generation is None:
        return PreparedRun("missing")
    if generation.status == "running" and _is_stale(generation.started_at):
        previous = generation.status
        _fail(generation, "worker_lost", {"error_type": "WorkerLost"})
        await _log_generation(session, generation, previous, "worker")
        return PreparedRun("stale_failed")
    log_event(
        logging.INFO,
        "generation_skipped",
        generation_id=str(generation.id),
        project_id=str(generation.project_id),
        inference_endpoint_id=str(generation.inference_endpoint_id),
        from_status=generation.status,
        to_status=generation.status,
        source="worker",
    )
    return PreparedRun("skipped")


async def apply_vast_result(
    session: AsyncSession,
    generation_id: UUID,
    result: dict[str, Any],
) -> bool:
    generation = await _lock(session, generation_id)
    if generation is None:
        return False
    generation.raw_provider_response = result
    terminal, body = _interpret_vast(result)
    _assign_outputs(generation, body.get("output"), overwrite=True)
    _fill_timings(generation, body.get("timings"))
    latency = _latency_ms(result.get("latency"))
    if latency is not None and generation.vast_latency_ms is None:
        generation.vast_latency_ms = latency
    previous = generation.status
    if _allow(generation.status, terminal):
        _finish(generation, terminal, body, result.get("status"))
        await _log_generation(session, generation, previous, "vast")
        # The wrapper sends its own webhook for anything it answered with a status.
        return terminal == "failed" and not isinstance(body.get("status"), str)
    generation.updated_at = _now()
    return False


async def apply_worker_failure(
    session: AsyncSession,
    generation_id: UUID,
    exc: Exception,
) -> bool:
    generation = await _lock(session, generation_id)
    if generation is None or not _allow(generation.status, "failed"):
        return False
    previous = generation.status
    details: dict[str, Any] = {"error_type": type(exc).__name__}
    if isinstance(exc, VastTransportError) and exc.status_code is not None:
        details["status_code"] = exc.status_code
    _fail(generation, type(exc).__name__, details)
    await _log_generation(session, generation, previous, "worker")
    return True


async def sweep_stuck_generations() -> int:
    now = _now()
    running_cutoff = now - timedelta(seconds=STUCK_RUNNING_SECONDS)
    queued_cutoff = now - timedelta(seconds=STUCK_QUEUED_SECONDS)
    async with session_scope() as session:
        stuck = (
            await session.scalars(
                select(Generation)
                .where(
                    or_(
                        and_(
                            Generation.status == "running",
                            or_(
                                Generation.started_at.is_(None),
                                Generation.started_at < running_cutoff,
                            ),
                        ),
                        and_(Generation.status == "queued", Generation.queued_at < queued_cutoff),
                    )
                )
                .order_by(Generation.created_at)
                .limit(SWEEP_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for generation in stuck:
            previous = generation.status
            if previous == "running":
                _fail(generation, "worker_lost", {"error_type": "WorkerLost"})
            else:
                _fail(generation, "never_started", {"error_type": "NeverStarted"})
            await _log_generation(session, generation, previous, "sweeper")
        failed_ids = [generation.id for generation in stuck]
    for generation_id in failed_ids:
        await notify_failure(generation_id)
    return len(failed_ids)


async def notify_failure(generation_id: UUID) -> None:
    try:
        async with session_scope() as session:
            generation = await session.get(Generation, generation_id)
            if generation is None or generation.status != "failed":
                return
            project = await session.get(Project, generation.project_id)
            if project is None:
                return
            destination = generation.webhook_url_override or project.webhook_url
            if not destination:
                return
            secret = decrypt_secret(project.webhook_secret_enc)
            raw = json.dumps(_failure_webhook(generation), default=str).encode("utf-8")
    except Exception as exc:
        log_event(
            logging.ERROR,
            "failure_webhook_failed",
            generation_id=str(generation_id),
            error_type=type(exc).__name__,
        )
        return
    signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    await _forward_webhook(destination, raw, signature, generation_id)


def _failure_webhook(generation: Generation) -> dict[str, Any]:
    extra = dict(generation.webhook_extra_params)
    extra["project_id"] = str(generation.project_id)
    extra["generation_id"] = str(generation.id)
    return {
        "id": str(generation.id),
        "status": "failed",
        "message": generation.error_message or "Generation failed",
        "output": [],
        "timings": {},
        "extra": extra,
    }


async def record_webhook(raw: bytes, signature: str | None) -> None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise WebhookError(400, "Invalid webhook") from None
    if not isinstance(parsed, dict):
        raise WebhookError(400, "Invalid webhook")
    extra = parsed.get("extra")
    if not isinstance(extra, dict):
        raise WebhookError(400, "Invalid webhook")
    generation_id = _uuid_or_none(extra.get("generation_id"))
    project_id = _uuid_or_none(extra.get("project_id"))
    if generation_id is None or project_id is None:
        raise WebhookError(400, "Invalid webhook")
    wrapper_id = parsed.get("id")
    if isinstance(wrapper_id, str) and wrapper_id != str(generation_id):
        raise WebhookError(400, "Invalid webhook")

    async with session_scope() as session:
        generation = await _lock(session, generation_id)
        if generation is None:
            raise WebhookError(404, "Unknown generation")
        project = await session.get(Project, generation.project_id)
        if project is None:
            raise WebhookError(404, "Unknown generation")
        secret = decrypt_secret(project.webhook_secret_enc)
        if not verify_webhook_signature(raw, signature, secret):
            raise WebhookError(401, "Invalid signature")
        if project.id != project_id:
            raise WebhookError(400, "Project mismatch")
        await _apply_webhook(session, generation, parsed)
        destination = generation.webhook_url_override or project.webhook_url
    if destination:
        await _forward_webhook(destination, raw, signature, generation_id)


async def _forward_webhook(
    destination: str,
    raw: bytes,
    signature: str | None,
    generation_id: UUID,
) -> None:
    headers = {"Content-Type": "application/json"}
    if signature:
        headers["X-Webhook-Signature"] = signature
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(destination, content=raw, headers=headers)
            response.raise_for_status()
    except Exception as exc:
        log_event(
            logging.ERROR,
            "webhook_forward_failed",
            generation_id=str(generation_id),
            error_type=type(exc).__name__,
        )


async def _apply_webhook(
    session: AsyncSession,
    generation: Generation,
    payload: dict[str, Any],
) -> None:
    status = payload.get("status") if isinstance(payload.get("status"), str) else ""
    incoming_terminal = status == "completed" or status in _WRAPPER_FAILURES
    if incoming_terminal or not _stored_webhook_is_terminal(generation.webhook_payload):
        generation.webhook_payload = payload
    if not incoming_terminal:
        generation.updated_at = _now()
        return
    mapped: Literal["completed", "failed"] = "completed" if status == "completed" else "failed"
    _assign_outputs(generation, payload.get("output"), overwrite=False)
    _fill_timings(generation, payload.get("timings"))
    previous = generation.status
    if _allow(generation.status, mapped):
        _finish(generation, mapped, payload, None)
        await _log_generation(session, generation, previous, "webhook")
        return
    generation.updated_at = _now()


async def _build_context(session: AsyncSession, generation_id: UUID) -> RunContext:
    generation = await session.get(Generation, generation_id)
    if generation is None:
        raise NotFoundError("Generation not found")
    project = await session.get(Project, generation.project_id)
    endpoint = await session.get(InferenceEndpoint, generation.inference_endpoint_id)
    if project is None or endpoint is None:
        raise NotFoundError("Generation is missing its project or endpoint")
    payload = build_vast_payload(
        generation_id=str(generation.id),
        project_id=str(project.id),
        workflow_json=generation.workflow_json,
        webhook_extra_params=generation.webhook_extra_params,
        s3_access_key_id=decrypt_secret(project.s3_access_key_id_enc),
        s3_secret_access_key=decrypt_secret(project.s3_secret_access_key_enc),
        s3_endpoint_url=project.s3_endpoint_url,
        s3_bucket_name=project.s3_bucket_name,
        s3_region=project.s3_region,
        webhook_secret=decrypt_secret(project.webhook_secret_enc),
    )
    cleaned = redact(payload)
    if isinstance(cleaned, dict):
        generation.sanitized_provider_request = cleaned
    generation.updated_at = _now()
    return RunContext(
        generation_id=generation.id,
        vast_endpoint_name=endpoint.vast_endpoint_name,
        payload=payload,
    )


async def _mark_publish_failed(session: AsyncSession, generation_id: UUID) -> None:
    generation = await _lock(session, generation_id)
    if generation is None or generation.status != "queued":
        return
    previous = generation.status
    _fail(generation, "publish_failed", {"error_type": "PublishError"})
    await _log_generation(session, generation, previous, "api")


def _interpret_vast(
    result: dict[str, Any],
) -> tuple[Literal["completed", "failed"], dict[str, Any]]:
    response = result.get("response")
    body = response if isinstance(response, dict) else {}
    wrapper_status = body.get("status") if isinstance(body.get("status"), str) else ""
    if wrapper_status == "completed":
        return "completed", body
    if wrapper_status in _WRAPPER_FAILURES or not result.get("ok"):
        return "failed", body
    if result.get("ok") and wrapper_status == "":
        return "completed", body
    return "failed", body


def _finish(
    generation: Generation,
    terminal: Literal["completed", "failed"],
    body: dict[str, Any],
    http_status: object,
) -> None:
    if terminal == "completed":
        generation.status = "completed"
        generation.completed_at = generation.completed_at or _now()
        generation.updated_at = generation.completed_at
        generation.error_message = None
        generation.error_details = None
        return
    message = _message(body)
    details = {
        "status": body.get("status"),
        "http_status": http_status if isinstance(http_status, int) else None,
        "message": message,
    }
    _fail(generation, message, details)


def _fail(generation: Generation, message: str, details: dict[str, Any]) -> None:
    generation.status = "failed"
    generation.failed_at = generation.failed_at or _now()
    generation.updated_at = generation.failed_at
    generation.error_message = message[:2000]
    generation.error_details = details


def _assign_outputs(generation: Generation, outputs: object, *, overwrite: bool) -> None:
    if not isinstance(outputs, list) or not outputs:
        return
    if generation.outputs and not overwrite:
        return
    generation.outputs = outputs


def _fill_timings(generation: Generation, timings: object) -> None:
    if not isinstance(timings, dict):
        return
    for name in ("preprocess_ms", "generation_ms", "postprocess_ms", "total_ms"):
        if getattr(generation, name) is not None:
            continue
        parsed = _millis(timings.get(name))
        if parsed is not None:
            setattr(generation, name, parsed)


def _stored_webhook_is_terminal(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    status = payload.get("status")
    if not isinstance(status, str):
        return False
    return status == "completed" or status in _WRAPPER_FAILURES


def _allow(current: str, new: str) -> bool:
    if new != "completed" and new != "failed":
        return False
    if current == "queued" or current == "running":
        return True
    return current == "failed" and new == "completed"


def _message(body: dict[str, Any]) -> str:
    for key in ("message", "error"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Generation failed"


def _millis(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or value > 2_000_000_000:
        return None
    return int(value)


def _latency_ms(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return _millis(value * 1000)


def _is_stale(started_at: datetime | None) -> bool:
    if started_at is None:
        return True
    moment = started_at if started_at.tzinfo is not None else started_at.replace(tzinfo=UTC)
    limit = timedelta(seconds=VERCEL_MAX_DURATION_SECONDS)
    return _now() - moment > limit


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid_or_none(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


async def _lock(session: AsyncSession, generation_id: UUID) -> Generation | None:
    return await session.get(Generation, generation_id, with_for_update=True)


async def _load_project(
    session: AsyncSession,
    *,
    project_id: UUID | None,
    slug: str | None,
) -> Project:
    project: Project | None
    if project_id is not None:
        project = await session.get(Project, project_id)
    elif slug is not None:
        project = await session.scalar(select(Project).where(Project.slug == slug))
    else:
        project = None
    if project is None:
        raise NotFoundError("Project not found")
    return project


async def _log_generation(
    session: AsyncSession,
    generation: Generation,
    previous: str,
    source: str,
) -> None:
    endpoint_name = await session.scalar(
        select(InferenceEndpoint.vast_endpoint_name).where(
            InferenceEndpoint.id == generation.inference_endpoint_id
        )
    )
    log_transition(
        failed=generation.status == "failed",
        generation_id=str(generation.id),
        project_id=str(generation.project_id),
        inference_endpoint_id=str(generation.inference_endpoint_id),
        vast_endpoint_name=endpoint_name or "",
        from_status=previous,
        to_status=generation.status,
        queued_at=_iso(generation.queued_at),
        started_at=_iso(generation.started_at),
        completed_at=_iso(generation.completed_at),
        queue_ms=queue_duration_ms(generation),
        generation_ms=generation.generation_ms,
        total_ms=total_duration_ms(generation),
        source=source,
        error_message=generation.error_message,
    )


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
