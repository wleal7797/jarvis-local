"""Inyección de dependencias de FastAPI.

Los controladores piden lo que necesitan con `Depends(...)` y no crean nada por su cuenta.
Esto permite reemplazar piezas en las pruebas.
"""

from typing import Annotated

import httpx
from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.services.health_service import HealthService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Cliente HTTP compartido, creado al arrancar la app (ver `lifespan` en main.py)."""
    return request.app.state.http


HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]


def get_health_service(settings: SettingsDep, http: HttpClientDep) -> HealthService:
    return HealthService(settings, http)
