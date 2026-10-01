from vast_inferencer.models import (
    GenerationDetail,
    GenerationListItem,
    GenerationStatus,
    InferenceEndpointOut,
    ProjectOut,
    SanitizedS3,
)
from vast_inferencer.tables import Generation, InferenceEndpoint, Project


def endpoint_out(endpoint: InferenceEndpoint, project_count: int = 0) -> InferenceEndpointOut:
    return InferenceEndpointOut(
        id=endpoint.id,
        name=endpoint.name,
        vast_endpoint_name=endpoint.vast_endpoint_name,
        enabled=endpoint.enabled,
        project_count=project_count,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


def project_out(project: Project, endpoint: InferenceEndpoint) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        slug=project.slug,
        inference_endpoint_id=project.inference_endpoint_id,
        inference_endpoint_name=endpoint.name,
        vast_endpoint_name=endpoint.vast_endpoint_name,
        s3=SanitizedS3(
            endpoint_url=project.s3_endpoint_url,
            bucket_name=project.s3_bucket_name,
            region=project.s3_region,
        ),
        webhook_url=project.webhook_url,
        webhook_secret_set=bool(project.webhook_secret_enc),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def generation_item(
    generation: Generation,
    project: Project,
    endpoint: InferenceEndpoint,
) -> GenerationListItem:
    return GenerationListItem(
        id=generation.id,
        status=generation_status(generation.status),
        project_id=project.id,
        project_name=project.name,
        project_slug=project.slug,
        inference_endpoint_id=endpoint.id,
        inference_endpoint_name=endpoint.name,
        vast_endpoint_name=endpoint.vast_endpoint_name,
        created_at=generation.created_at,
        queue_ms=queue_duration_ms(generation),
        generation_ms=generation.generation_ms,
        total_ms=total_duration_ms(generation),
    )


def generation_detail(
    generation: Generation,
    project: Project,
    endpoint: InferenceEndpoint,
) -> GenerationDetail:
    return GenerationDetail(
        id=generation.id,
        status=generation_status(generation.status),
        project_id=project.id,
        project_name=project.name,
        project_slug=project.slug,
        inference_endpoint_id=endpoint.id,
        inference_endpoint_name=endpoint.name,
        vast_endpoint_name=endpoint.vast_endpoint_name,
        created_at=generation.created_at,
        queued_at=generation.queued_at,
        started_at=generation.started_at,
        completed_at=generation.completed_at,
        failed_at=generation.failed_at,
        updated_at=generation.updated_at,
        queue_ms=queue_duration_ms(generation),
        preprocess_ms=generation.preprocess_ms,
        generation_ms=generation.generation_ms,
        postprocess_ms=generation.postprocess_ms,
        total_ms=total_duration_ms(generation),
        vast_latency_ms=generation.vast_latency_ms,
        attempts=generation.attempts,
        qstash_message_id=generation.qstash_message_id,
        workflow_json=generation.workflow_json,
        webhook_extra_params=generation.webhook_extra_params,
        webhook_url=generation.webhook_url_override or project.webhook_url,
        webhook_url_override=generation.webhook_url_override,
        outputs=generation.outputs,
        sanitized_provider_request=generation.sanitized_provider_request,
        raw_provider_response=generation.raw_provider_response,
        webhook_payload=generation.webhook_payload,
        error_message=generation.error_message,
        error_details=generation.error_details,
        forwarded_status=generation.forwarded_status,
        forwarded_at=generation.forwarded_at,
    )


def queue_duration_ms(generation: Generation) -> int | None:
    if generation.queued_at is None or generation.started_at is None:
        return None
    return max(0, int((generation.started_at - generation.queued_at).total_seconds() * 1000))


def total_duration_ms(generation: Generation) -> int | None:
    if generation.total_ms is not None:
        return generation.total_ms
    finished = generation.completed_at or generation.failed_at
    if finished is None or generation.created_at is None:
        return None
    return max(0, int((finished - generation.created_at).total_seconds() * 1000))


def generation_status(value: str) -> GenerationStatus:
    if value == "queued":
        return "queued"
    if value == "running":
        return "running"
    if value == "completed":
        return "completed"
    return "failed"
