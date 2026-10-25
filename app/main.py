"""Punto de entrada de la API JARVIS.

Arranque en desarrollo:
    .venv\\Scripts\\python -m app
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from app.controllers import (
    chat_controller,
    health_controller,
    knowledge_controller,
    page_controller,
    voice_controller,
)
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.logging import setup_logging
from app.services.stt_service import FasterWhisperSTT, WhisperSettings
from app.services.tts_service import PiperSettings, PiperTTS

logger = logging.getLogger("jarvis")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.http = httpx.AsyncClient(timeout=settings.ollama_timeout_seconds)
    # El motor no se conecta todavía: abre conexiones cuando se usan por primera vez.
    app.state.engine = create_engine(settings.database_url())
    app.state.session_factory = create_session_factory(app.state.engine)
    # Whisper no se carga aquí: se carga la primera vez que alguien habla.
    app.state.stt = FasterWhisperSTT(
        WhisperSettings(
            model=settings.stt_model,
            language=settings.stt_language,
            threads=settings.stt_threads,
            initial_prompt=settings.stt_initial_prompt,
            idle_unload_seconds=settings.stt_idle_unload_seconds,
        )
    )
    app.state.tts = PiperTTS(
        PiperSettings(
            voices_dir=settings.tts_voices_dir,
            voice=settings.tts_voice,
            length_scale=settings.tts_length_scale,
            idle_unload_seconds=settings.tts_idle_unload_seconds,
        )
    )
    stt_watcher = asyncio.create_task(app.state.stt.run_idle_watcher())
    tts_watcher = asyncio.create_task(app.state.tts.run_idle_watcher())
    logger.info("JARVIS iniciado", extra={"environment": settings.environment})
    yield
    for watcher in (stt_watcher, tts_watcher):
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
    await app.state.http.aclose()
    await app.state.engine.dispose()
    logger.info("JARVIS detenido")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        description="Asistente personal con IA 100 % local.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        logger.info(
            "petición",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
        return response

    @app.get("/api", include_in_schema=False)
    async def api_root() -> dict[str, str]:
        return {"message": f"{settings.app_name} en línea", "docs": "/docs", "health": "/health"}

    app.mount("/static", StaticFiles(directory=page_controller.VIEWS_DIR / "static"), "static")
    app.include_router(page_controller.router)
    app.include_router(health_controller.router)
    app.include_router(chat_controller.router)
    app.include_router(chat_controller.ws_router)
    app.include_router(knowledge_controller.router)
    app.include_router(voice_controller.router)
    return app


app = create_app()
