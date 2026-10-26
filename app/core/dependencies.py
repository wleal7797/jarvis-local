"""Inyección de dependencias de FastAPI.

Los controladores piden lo que necesitan con `Depends(...)` y no crean nada por su cuenta.
Esto permite reemplazar piezas en las pruebas.
"""

import secrets
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
from app.services.auth_service import SESSION_COOKIE, AuthService
from app.services.chat_service import ChatService
from app.services.embedding_service import Embedder, OllamaEmbedder
from app.services.health_service import DatabaseProbe, HealthService
from app.services.ingestion import IngestionService
from app.services.llm import LLMProvider, OllamaProvider
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService, RetrievalSettings
from app.services.stt_service import SpeechToText
from app.services.training_service import TrainingService
from app.services.tts_service import TextToSpeech
from app.services.voice_status import VoiceStatusHub

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


def get_memory_service(
    settings: SettingsDep,
    factory: SessionFactoryDep,
    llm: Annotated[LLMProvider, Depends(get_llm)],
    embedder: EmbedderDep,
) -> MemoryService:
    return MemoryService(
        factory,
        llm,
        embedder,
        settings.ollama_chat_model,
        budget=settings.memory_token_budget,
        learning=settings.memory_enabled,
    )


MemoryServiceDep = Annotated[MemoryService, Depends(get_memory_service)]


def get_training_service(factory: SessionFactoryDep) -> TrainingService:
    return TrainingService(factory)


TrainingServiceDep = Annotated[TrainingService, Depends(get_training_service)]


def get_chat_service(
    settings: SettingsDep,
    factory: SessionFactoryDep,
    llm: Annotated[LLMProvider, Depends(get_llm)],
    embedder: EmbedderDep,
    memory: MemoryServiceDep,
) -> ChatService:
    retriever_factory = None
    if settings.rag_enabled:
        config = retrieval_settings(settings)

        def retriever_factory(session: AsyncSession) -> RetrievalService:
            return RetrievalService(session, embedder, config)

    return ChatService(
        factory,
        llm,
        settings.ollama_chat_model,
        retriever_factory,
        voice_context_tokens=settings.rag_voice_context_tokens,
        voice_max_tokens=settings.voice_max_tokens,
        memory=memory if settings.memory_enabled else None,
    )


def get_auth_service(conn: HTTPConnection) -> AuthService | None:
    """Uno para toda la app (lo crea `main.py`; guarda los intentos fallidos)."""
    return getattr(conn.app.state, "auth", None)


AuthServiceDep = Annotated[AuthService | None, Depends(get_auth_service)]


async def _owner(settings: Settings, session: AsyncSession) -> User:
    user = await UserRepository(session).get_by_username(settings.default_username)
    if user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No existe el usuario por defecto. Ejecuta: python -m scripts.seed",
        )
    return user


async def get_optional_user(
    conn: HTTPConnection, settings: SettingsDep, session: SessionDep, auth: AuthServiceDep
) -> User | None:
    """¿Quién hace la petición? (Etapa 11)

    1. El agente de voz de este PC: `Authorization: Bearer <data/agent.token>` → el dueño.
    2. Con el inicio de sesión apagado (`AUTH_ENABLED=false`): el dueño.
    3. Si no: la cookie de sesión firmada. Sin ella (o vencida), nadie.
    """
    header = conn.headers.get("authorization", "")
    agent_token = getattr(conn.app.state, "agent_token", None)
    if (
        agent_token
        and header.startswith("Bearer ")
        and secrets.compare_digest(header[7:].encode(), agent_token.encode())
    ):
        return await _owner(settings, session)
    if not settings.auth_enabled:
        return await _owner(settings, session)
    if auth is None:
        return None
    found = auth.read(conn.cookies.get(SESSION_COOKIE))
    if found is None:
        return None
    user = await UserRepository(session).get(found.user_id)
    return user if user is not None and user.is_active else None


OptionalUserDep = Annotated[User | None, Depends(get_optional_user)]


async def get_current_user(user: OptionalUserDep) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Inicie sesión para continuar.")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: str):
    """Dependencia: sólo pasan los usuarios con alguno de esos roles."""

    async def check(user: CurrentUserDep) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permiso para esto.")
        return user

    return check


# Familia y dueño: documentos, memoria, calificaciones y ajustes de voz.
require_member = require_roles("owner", "member")
# Sólo el dueño: usuarios y lo que usa el agente de voz.
require_owner = require_roles("owner")
MemberDep = Annotated[User, Depends(require_member)]
OwnerDep = Annotated[User, Depends(require_owner)]
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


def get_tts(conn: HTTPConnection) -> TextToSpeech:
    """Voz compartida por toda la app (se carga al primer uso, ~60 MB)."""
    return conn.app.state.tts


TextToSpeechDep = Annotated[TextToSpeech, Depends(get_tts)]


def get_voice_status(conn: HTTPConnection) -> VoiceStatusHub:
    """Estado del agente de voz (uno para toda la app, creado en `main.py`)."""
    return conn.app.state.voice_status


VoiceStatusDep = Annotated[VoiceStatusHub, Depends(get_voice_status)]
LLMDep = Annotated[LLMProvider, Depends(get_llm)]
