"""Comprueba que JARVIS y sus dependencias estén funcionando: Ollama y PostgreSQL."""

import logging
import time
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import Settings
from app.schemas.health import DependencyHealth, HealthOut

logger = logging.getLogger(__name__)

# Función que se conecta a la BD y devuelve la versión de pgvector (o lanza un error).
DatabaseProbe = Callable[[], Awaitable[str]]


class HealthService:
    def __init__(
        self, settings: Settings, http: httpx.AsyncClient, db_probe: DatabaseProbe
    ) -> None:
        self._settings = settings
        self._http = http
        self._db_probe = db_probe

    async def check(self) -> HealthOut:
        dependencies = {
            "ollama": await self._check_ollama(),
            "database": await self._check_database(),
        }
        all_up = all(d.status == "up" for d in dependencies.values())
        return HealthOut(
            status="ok" if all_up else "degraded",
            app=self._settings.app_name,
            version=self._settings.app_version,
            environment=self._settings.environment,
            dependencies=dependencies,
        )

    async def _check_ollama(self) -> DependencyHealth:
        start = time.perf_counter()
        try:
            response = await self._http.get(
                f"{self._settings.ollama_base_url}/api/version", timeout=3.0
            )
            response.raise_for_status()
            version = response.json().get("version", "?")
        except httpx.HTTPError as exc:
            logger.warning("Ollama no responde", extra={"error": str(exc)})
            return DependencyHealth(status="down", detail="Ollama no responde")
        return DependencyHealth(
            status="up", detail=f"Ollama {version}", latency_ms=_elapsed_ms(start)
        )

    async def _check_database(self) -> DependencyHealth:
        start = time.perf_counter()
        try:
            pgvector_version = await self._db_probe()
        except Exception as exc:  # cualquier fallo de conexión cuenta como "down"
            logger.warning("PostgreSQL no responde", extra={"error": str(exc)})
            return DependencyHealth(status="down", detail="PostgreSQL no responde")
        return DependencyHealth(
            status="up",
            detail=f"PostgreSQL + pgvector {pgvector_version}",
            latency_ms=_elapsed_ms(start),
        )


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
