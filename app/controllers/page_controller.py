"""Controlador de páginas: devuelve las vistas HTML (la "V" de MVC)."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.dependencies import SettingsDep

VIEWS_DIR = Path(__file__).resolve().parent.parent / "views"
templates = Jinja2Templates(directory=VIEWS_DIR / "templates")

router = APIRouter(include_in_schema=False)


@router.get("/favicon.ico")
async def favicon() -> FileResponse:
    """Los navegadores piden /favicon.ico aunque la página indique otro ícono."""
    return FileResponse(VIEWS_DIR / "static" / "img" / "jarvis.svg", media_type="image/svg+xml")


@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request, settings: SettingsDep) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "chat.html",
        {"app_name": settings.app_name, "app_version": settings.app_version},
    )
