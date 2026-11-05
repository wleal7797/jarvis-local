"""Contrato JSON de la respuesta de /health (la "vista" de la API)."""

from typing import Literal

from pydantic import BaseModel

Status = Literal["ok", "degraded"]
DependencyStatus = Literal["up", "down"]


class DependencyHealth(BaseModel):
    status: DependencyStatus
    detail: str | None = None
    latency_ms: int | None = None


class HealthOut(BaseModel):
    status: Status
    app: str
    version: str
    environment: str
    # Protocolo Odiseo: True = este proceso no puede conectarse a la red.
    odiseo: bool = False
    dependencies: dict[str, DependencyHealth]
