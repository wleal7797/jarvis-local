"""Controlador de salud: ¿está JARVIS funcionando?"""

import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.core.dependencies import get_health_service
from app.schemas.health import HealthOut
from app.services.health_service import HealthService

router = APIRouter(tags=["sistema"])


@router.get("/health", response_model=HealthOut, summary="Estado de JARVIS y sus dependencias")
async def health(service: Annotated[HealthService, Depends(get_health_service)]) -> HealthOut:
    return await service.check()


def caddy_root_certificate() -> Path:
    """Certificado raíz de la autoridad local de Caddy (lo crea Caddy al arrancar)."""
    return (
        Path(os.environ.get("APPDATA", "")) / "Caddy" / "pki" / "authorities" / "local" / "root.crt"
    )


@router.get(
    "/certificado",
    summary="Certificado de JARVIS para instalar en el celular (Etapa 11)",
    response_class=FileResponse,
)
async def certificate() -> Response:
    """Público a propósito: un certificado raíz no es secreto (sólo la clave privada lo es,
    y esa nunca sale de la carpeta de Caddy). Instalarlo hace que el celular confíe en
    https://<ip-del-pc> y permita usar el micrófono."""
    path = caddy_root_certificate()
    if not path.exists():
        return PlainTextResponse(
            "Todavía no hay certificado: encienda JARVIS con Caddy (.\scripts\jarvis.ps1 iniciar).",
            status_code=404,
        )
    return FileResponse(path, media_type="application/x-x509-ca-cert", filename="jarvis-ca.crt")
