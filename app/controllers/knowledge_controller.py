"""Controlador de conocimiento: agregar texto, listar fuentes y probar la búsqueda.

La carga de archivos, páginas web y Wikipedia llega en la Etapa 6.
"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.dependencies import CurrentUserDep, EmbedderDep, SessionDep, SettingsDep
from app.core.dependencies import retrieval_settings as build_retrieval_settings
from app.models import Chunk, Document, Source
from app.schemas.knowledge import IndexOut, SearchResultOut, SourceOut, TextIn
from app.services.embedding_service import EmbeddingError
from app.services.knowledge_service import KnowledgeService
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/api/knowledge", tags=["conocimiento"])

EMBEDDINGS_DOWN = "No se pudieron calcular los embeddings: ¿está Ollama encendido?"


@router.post(
    "/text",
    response_model=IndexOut,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar un texto al conocimiento de JARVIS",
)
async def add_text(body: TextIn, user: CurrentUserDep, session: SessionDep, embedder: EmbedderDep):
    service = KnowledgeService(session, embedder)
    owner_id = user.id if body.personal else None
    source = await service.get_or_create_source(
        "manual", body.source_name, owner_user_id=owner_id, is_personal=body.personal
    )
    try:
        result = await service.add_text(source, body.title, body.text)
    except EmbeddingError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, EMBEDDINGS_DOWN) from None
    return IndexOut(
        document_id=result.document.id,
        title=result.document.title,
        chunks=result.chunks,
        created=result.created,
    )


@router.get("/sources", response_model=list[SourceOut], summary="Fuentes de conocimiento")
async def list_sources(user: CurrentUserDep, session: SessionDep):
    stmt = (
        select(
            Source,
            func.count(func.distinct(Document.id)).label("documents"),
            func.count(Chunk.id).label("chunks"),
        )
        .outerjoin(Document, Document.source_id == Source.id)
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .where((Source.is_personal.is_(False)) | (Source.owner_user_id == user.id))
        .group_by(Source.id)
        .order_by(Source.name)
    )
    return [
        SourceOut(
            id=row.Source.id,
            kind=row.Source.kind,
            name=row.Source.name,
            is_personal=row.Source.is_personal,
            documents=row.documents,
            chunks=row.chunks,
        )
        for row in (await session.execute(stmt)).all()
    ]


@router.get(
    "/search",
    response_model=list[SearchResultOut],
    summary="Probar la búsqueda híbrida (lo que JARVIS leería antes de responder)",
)
async def search(
    user: CurrentUserDep,
    session: SessionDep,
    embedder: EmbedderDep,
    settings: SettingsDep,
    q: str = Query(min_length=1, max_length=500),
):
    service = RetrievalService(session, embedder, build_retrieval_settings(settings))
    try:
        results = await service.search(q, owner_user_id=user.id)
    except EmbeddingError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, EMBEDDINGS_DOWN) from None
    return [SearchResultOut(**vars(r)) for r in results]
