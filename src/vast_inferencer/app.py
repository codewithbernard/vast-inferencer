import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from vast_inferencer.config import get_settings
from vast_inferencer.logging import configure_logging, log_event
from vast_inferencer.routes import generations, health, internal


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().log_level)
    yield


app = FastAPI(title="Vast Inferencer", lifespan=lifespan)
app.include_router(health.router)
app.include_router(generations.router)
app.include_router(internal.router)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> Response:
    if isinstance(exc, RequestValidationError):
        return await request_validation_exception_handler(request, exc)
    if isinstance(exc, StarletteHTTPException):
        return await http_exception_handler(request, exc)
    log_event(logging.ERROR, "unhandled_error", error_type=type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
