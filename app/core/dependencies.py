"""Inyección de dependencias de FastAPI.

Los controladores piden lo que necesitan con `Depends(...)` y no crean nada por su cuenta.
Esto permite reemplazar piezas en las pruebas.
"""

from collections.abc import AsyncIterator
from functools import partial
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.requests import HTTPConnection

from app.core.config import Settings, get_settings
from app.core.database import ping, session_scope
from app.models import User
from app.repositories import UserRepository
from app.services.chat_service import ChatService
from app.services.embedding_service import Embedder, OllamaEmbedder
from app.services.health_service import DatabaseProbe, HealthService
from app.services.ingestion import IngestionService
from app.services.llm import LLMProvider, OllamaProvider
from app.services.retrieval_service import RetrievalService, RetrievalSettings
from app.services.stt_service import SpeechToText

SettingsDep = Annotated[Settings, Depends(get_settings)]


# `HTTPConnection` sirve tanto para peticiones HTTP como para WebSocket.


def get_http_client(conn: HTTPConnection) -> httpx.AsyncClient:
    """Cliente HTTP compartido, creado al arrancar la app (ver `lifespan` en main.py)."""
    return conn.app.state.http


def get_engine(conn: HTTPConnection) -> AsyncEngine:
    return conn.app.state.engine


def get_session_factory(conn: HTTPConnection) -> async_sessionmaker[AsyncSession]:
    return conn.app.state.session_factory


async def get_session(
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    """Una sesión de base de datos por petición."""
    async for session in session_scope(factory):
        yield session


def get_db_probe(engine: Annotated[AsyncEngine, Depends(get_engine)]) -> DatabaseProbe:
    return partial(ping, engine)


HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]


def get_health_service(
    settings: SettingsDep,
    http: HttpClientDep,
    db_probe: Annotated[DatabaseProbe, Depends(get_db_probe)],
) -> HealthService:
    return HealthService(settings, http, db_probe)


def get_llm(settings: SettingsDep, http: HttpClientDep) -> LLMProvider:
    return OllamaProvider(http, settings.ollama_base_url, settings.ollama_chat_model)


def get_embedder(settings: SettingsDep, http: HttpClientDep) -> Embedder:
    return OllamaEmbedder(
        http,
        settings.ollama_base_url,
        settings.ollama_embed_model,
        use_gpu=settings.ollama_embed_on_gpu,
        threads=settings.ollama_embed_threads,
        keep_alive=settings.ollama_embed_keep_alive,
    )


EmbedderDep = Annotated[Embedder, Depends(get_embedder)]


def retrieval_settings(settings: Settings) -> RetrievalSettings:
    return RetrievalSettings(
        top_k=settings.rag_top_k,
        min_similarity=settings.rag_min_similarity,
        min_similarity_with_keywords=settings.rag_min_similarity_with_keywords,
    )


def get_chat_service(
    settings: SettingsDep,
    factory: SessionFactoryDep,
    llm: Annotated[LLMProvider, Depends(get_llm)],
    embedder: EmbedderDep,
) -> ChatService:
    retriever_factory = None
    if settings.rag_enabled:
        config = retrieval_settings(settings)

        def retriever_factory(session: AsyncSession) -> RetrievalService:
            return RetrievalService(session, embedder, config)

    return ChatService(factory, llm, settings.ollama_chat_model, retriever_factory)


async def get_current_user(settings: SettingsDep, session: SessionDep) -> User:
    """Usuario que está conversando.

    Mientras no exista el inicio de sesión (Etapa 11), siempre es el usuario por defecto
    que crea `scripts/seed.py`.
    """
    user = await UserRepository(session).get_by_username(settings.default_username)
    if user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No existe el usuario por defecto. Ejecuta: python -m scripts.seed",
        )
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


def get_ingestion_service(settings: SettingsDep, factory: SessionFactoryDep) -> IngestionService:
    return IngestionService(
        factory,
        uploads_dir=Path(settings.uploads_dir),
        allow_internet=settings.ingestion_allow_internet,
    )


IngestionServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]


def get_stt(conn: HTTPConnection) -> SpeechToText:
    """Whisper compartido (uno solo para toda la app: el modelo pesa ~250 MB en RAM)."""
    return conn.app.state.stt


SpeechToTextDep = Annotated[SpeechToText, Depends(get_stt)]
