"""Inyección de dependencias de FastAPI.

Los controladores piden lo que necesitan con `Depends(...)` y no crean nada por su cuenta.
Esto permite reemplazar piezas en las pruebas.
"""

from collections.abc import AsyncIterator
from functools import partial
from typing import Annotated

import httpx
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import ping, session_scope
from app.services.health_service import DatabaseProbe, HealthService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Cliente HTTP compartido, creado al arrancar la app (ver `lifespan` en main.py)."""
    return request.app.state.http


def get_engine(request: Request) -> AsyncEngine:
    return request.app.state.engine


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Una sesión de base de datos por petición."""
    async for session in session_scope(request.app.state.session_factory):
        yield session


def get_db_probe(engine: Annotated[AsyncEngine, Depends(get_engine)]) -> DatabaseProbe:
    return partial(ping, engine)


HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_health_service(
    settings: SettingsDep,
    http: HttpClientDep,
    db_probe: Annotated[DatabaseProbe, Depends(get_db_probe)],
) -> HealthService:
    return HealthService(settings, http, db_probe)
