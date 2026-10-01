import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

SRC = Path(__file__).resolve().parent
SRC_PATH = str(SRC)
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

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
from vast_inferencer.routes import (
    admin,
    generations,
    health,
    inference_endpoints,
    internal,
    playground,
    projects,
    webhooks,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().log_level)
    yield


app = FastAPI(title="Vast Inferencer", lifespan=lifespan)
app.include_router(playground.router)
app.include_router(admin.router)
app.include_router(health.router)
app.include_router(inference_endpoints.router)
app.include_router(projects.router)
app.include_router(generations.router)
app.include_router(internal.router)
app.include_router(webhooks.router)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> Response:
    if isinstance(exc, RequestValidationError):
        return await request_validation_exception_handler(request, exc)
    if isinstance(exc, StarletteHTTPException):
        return await http_exception_handler(request, exc)
    log_event(logging.ERROR, "unhandled_error", error_type=type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
