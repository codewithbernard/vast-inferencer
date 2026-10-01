from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_ADMIN_HTML = (Path(__file__).resolve().parent.parent / "admin" / "index.html").read_text(
    encoding="utf-8"
)


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin() -> HTMLResponse:
    return HTMLResponse(content=_ADMIN_HTML)
