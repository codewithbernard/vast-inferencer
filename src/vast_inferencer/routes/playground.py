import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from vast_inferencer.registry import PROJECTS

router = APIRouter()

_PLAYGROUND_HTML = (
    Path(__file__).resolve().parent.parent / "playground" / "index.html"
).read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def playground() -> HTMLResponse:
    project_ids_json = json.dumps(sorted(PROJECTS.keys()))
    html = _PLAYGROUND_HTML.replace("__PROJECT_IDS__", project_ids_json)
    return HTMLResponse(content=html)
