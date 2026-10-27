"""Controlador de conocimiento: agregar texto, archivos, páginas web y Wikipedia,
ver las tareas de ingesta, listar o borrar fuentes y probar la búsqueda.

Los archivos, la web y Wikipedia se **encolan**: el worker (`python -m worker`) los procesa.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select

from app.core.dependencies import (
    CurrentUserDep,
    EmbedderDep,
    IngestionServiceDep,
    SessionDep,
    SettingsDep,
    require_member,
)
from app.core.dependencies import retrieval_settings as build_retrieval_settings
from app.models import Chunk, Document, IngestionJob, Source
from app.repositories import JobRepository
from app.schemas.knowledge import (
    IndexOut,
    JobOut,
    SearchResultOut,
    SourceOut,
    TextIn,
    WebIn,
    WikipediaIn,
)
from app.services.embedding_service import EmbeddingError
from app.services.ingestion import IngestionError
from app.services.ingestion.file_loader import MAX_BYTES, SUPPORTED
from app.services.knowledge_service import KnowledgeService
from app.services.retrieval_service import RetrievalService

# Los invitados no ven documentos (ni de la casa ni personales).
router = APIRouter(
    prefix="/api/knowledge", tags=["conocimiento"], dependencies=[Depends(require_member)]
)

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


# ---------- Ingesta en segundo plano (Etapa 6) ----------


def job_label(job: IngestionJob) -> str:
    params = job.params or {}
    kind = params.get("type")
    if kind == "file":
        return params.get("filename", "Archivo")
    if kind == "web":
        pages = params.get("max_pages", 1)
        return f"{params.get('url')} ({pages} página{'s' if pages != 1 else ''})"
    if kind == "wikipedia":
        parts = []
        if params.get("titles"):
            titles = params["titles"]
            parts.append(
                ", ".join(titles[:3]) + (f" y {len(titles) - 3} más" if len(titles) > 3 else "")
            )
        if params.get("category"):
            parts.append(f"categoría {params['category']} (hasta {params.get('limit')})")
        return " · ".join(parts)
    return str(kind)


def to_job_out(job: IngestionJob, source: Source) -> JobOut:
    return JobOut(
        id=job.id,
        type=(job.params or {}).get("type", "?"),
        label=job_label(job),
        source_name=source.name,
        status=job.status,
        docs_done=job.docs_done,
        docs_total=job.docs_total,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


async def _job_out(session, job_id: int) -> JobOut:
    job = await session.get(IngestionJob, job_id)
    source = await session.get(Source, job.source_id)
    return to_job_out(job, source)


@router.post(
    "/files",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Subir un archivo (txt, md, pdf, docx, html) para indexarlo",
)
async def upload_file(
    user: CurrentUserDep,
    session: SessionDep,
    service: IngestionServiceDep,
    file: Annotated[UploadFile, File(description="Archivo a indexar")],
    personal: Annotated[bool, Form(description="Sólo lo verá quien lo sube")] = False,
):
    name = file.filename or "archivo"
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in SUPPORTED:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Formato no soportado. Usa: {', '.join(sorted(SUPPORTED))}",
        )
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "El archivo supera 20 MB")
    job = await service.enqueue_file(name, data, owner_user_id=user.id, personal=personal)
    return await _job_out(session, job.id)


@router.post(
    "/web",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Agregar una página web (y opcionalmente las de su mismo sitio)",
)
async def add_web(
    body: WebIn, user: CurrentUserDep, session: SessionDep, service: IngestionServiceDep
):
    try:
        job = await service.enqueue_web(str(body.url), body.max_pages)
    except IngestionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    return await _job_out(session, job.id)


@router.post(
    "/wikipedia",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Agregar artículos de Wikipedia por título o por categoría",
)
async def add_wikipedia(
    body: WikipediaIn, user: CurrentUserDep, session: SessionDep, service: IngestionServiceDep
):
    titles = [t.strip() for t in body.titles if t.strip()]
    if not titles and not body.category:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Indica títulos o una categoría")
    try:
        job = await service.enqueue_wikipedia(titles, body.category, body.limit, body.language)
    except IngestionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    return await _job_out(session, job.id)


@router.get("/jobs", response_model=list[JobOut], summary="Tareas de ingesta recientes")
async def list_jobs(user: CurrentUserDep, session: SessionDep):
    return [to_job_out(job, source) for job, source in await JobRepository(session).recent(user.id)]


@router.post(
    "/jobs/{job_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancelar una tarea en cola o en curso",
)
async def cancel_job(job_id: int, user: CurrentUserDep, service: IngestionServiceDep):
    if not await service.cancel(job_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "La tarea no existe o ya terminó")


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una fuente con todos sus documentos y fragmentos",
)
async def delete_source(source_id: int, user: CurrentUserDep, session: SessionDep):
    source = await session.get(Source, source_id)
    if source is None or (source.is_personal and source.owner_user_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fuente no encontrada")
    await session.delete(source)
