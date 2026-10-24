"""Controlador de salud: ¿está JARVIS funcionando?"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import get_health_service
from app.schemas.health import HealthOut
from app.services.health_service import HealthService

router = APIRouter(tags=["sistema"])


@router.get("/health", response_model=HealthOut, summary="Estado de JARVIS y sus dependencias")
async def health(service: Annotated[HealthService, Depends(get_health_service)]) -> HealthOut:
    return await service.check()
