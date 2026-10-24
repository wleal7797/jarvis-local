"""Comprueba que JARVIS y sus dependencias estén funcionando.

En la Etapa 1 sólo revisa Ollama. En la Etapa 2 se agrega PostgreSQL.
"""

import logging
import time

import httpx

from app.core.config import Settings
from app.schemas.health import DependencyHealth, HealthOut

logger = logging.getLogger(__name__)


class HealthService:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http

    async def check(self) -> HealthOut:
        dependencies = {"ollama": await self._check_ollama()}
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
        latency = int((time.perf_counter() - start) * 1000)
        return DependencyHealth(status="up", detail=f"Ollama {version}", latency_ms=latency)
