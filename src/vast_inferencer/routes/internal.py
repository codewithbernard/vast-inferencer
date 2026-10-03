import hmac
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from qstash.errors import SignatureError

from vast_inferencer.config import get_settings
from vast_inferencer.logging import log_event
from vast_inferencer.models import GenerationJob
from vast_inferencer.services.generations import run_claimed_generation, sweep_stuck_generations
from vast_inferencer.services.qstash import verify_delivery

router = APIRouter()


@router.get("/internal/sweep")
async def sweep(request: Request) -> JSONResponse:
    cron_secret = get_settings().cron_secret
    if cron_secret is None:
        return JSONResponse(status_code=503, content={"detail": "Sweeper not configured"})
    expected = f"Bearer {cron_secret.get_secret_value()}".encode()
    if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    failed = await sweep_stuck_generations()
    return JSONResponse(status_code=200, content={"failed": failed})


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
        outcome = await run_claimed_generation(job.generation_id)
    except Exception as exc:
        log_event(
            logging.ERROR,
            "generation_failed",
            generation_id=str(job.generation_id),
            error_type=type(exc).__name__,
            route="/internal/generations",
        )
        return JSONResponse(status_code=502, content={"detail": "Generation failed"})

    if outcome == "missing":
        return _non_retryable("Unknown generation")
    return JSONResponse(status_code=200, content={"ok": True})


def _non_retryable(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=489,
        content={"detail": detail},
        headers={"Upstash-NonRetryable-Error": "true"},
    )
