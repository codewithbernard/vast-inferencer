from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from vast_inferencer.services.generations import WebhookError, record_webhook

router = APIRouter()


@router.post("/webhooks/comfyui")
async def comfyui_webhook(request: Request) -> JSONResponse:
    raw = await request.body()
    try:
        await record_webhook(raw, request.headers.get("x-webhook-signature"))
    except WebhookError as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(status_code=200, content={"ok": True})
