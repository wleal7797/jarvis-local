"""Controlador de páginas: devuelve las vistas HTML (la "V" de MVC).

Sin sesión, todas las páginas llevan a `/login` (Etapa 11). Los invitados sólo ven el chat;
la página de usuarios es sólo del dueño.
"""

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.dependencies import OptionalUserDep, SettingsDep
from app.models import User

VIEWS_DIR = Path(__file__).resolve().parent.parent / "views"
templates = Jinja2Templates(directory=VIEWS_DIR / "templates")

ROLE_NAMES = {"owner": "Dueño", "member": "Familia", "guest": "Invitado"}


def asset_version() -> str:
    """Cambia cuando cambia cualquier archivo estático: obliga al navegador a no usar
    una copia vieja del CSS o del JS después de una actualización (`/static/x.css?v=…`)."""
    newest = max(f.stat().st_mtime for f in (VIEWS_DIR / "static").rglob("*") if f.is_file())
    return str(int(newest))


templates.env.globals["v"] = asset_version()
templates.env.globals["role_names"] = ROLE_NAMES

router = APIRouter(include_in_schema=False)


def _page(
    request: Request,
    settings,
    user: User | None,
    template: str,
    roles: tuple[str, ...] = ("owner", "member", "guest"),
) -> Response:
    if user is None:
        target = request.url.path
        return RedirectResponse(f"/login?next={quote(target)}", status_code=303)
    if user.role not in roles:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        template,
        {
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "user": user,
            "auth_enabled": settings.auth_enabled,
        },
    )


@router.get("/favicon.ico")
async def favicon() -> FileResponse:
    """Los navegadores piden /favicon.ico aunque la página indique otro ícono."""
    return FileResponse(VIEWS_DIR / "static" / "img" / "jarvis.svg", media_type="image/svg+xml")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, settings: SettingsDep, user: OptionalUserDep) -> Response:
    if user is not None and settings.auth_enabled:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"app_name": settings.app_name, "app_version": settings.app_version}
    )


@router.get("/conocimiento", response_class=HTMLResponse)
async def knowledge_page(request: Request, settings: SettingsDep, user: OptionalUserDep):
    return _page(request, settings, user, "knowledge.html", ("owner", "member"))


@router.get("/memoria", response_class=HTMLResponse)
async def memory_page(request: Request, settings: SettingsDep, user: OptionalUserDep):
    return _page(request, settings, user, "memory.html", ("owner", "member"))


@router.get("/usuarios", response_class=HTMLResponse)
async def users_page(request: Request, settings: SettingsDep, user: OptionalUserDep):
    return _page(request, settings, user, "users.html", ("owner",))


@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request, settings: SettingsDep, user: OptionalUserDep):
    return _page(request, settings, user, "chat.html")
