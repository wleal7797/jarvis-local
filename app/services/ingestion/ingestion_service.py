"""Encola y ejecuta tareas de ingesta: archivo, página web o Wikipedia.

- La API sólo **encola** (responde al instante).
- El worker (`python -m worker`) **ejecuta**: carga → fragmenta → vectoriza → guarda,
  documento por documento, actualizando el progreso para el panel web.
"""

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import IngestionJob, Source
from app.services.embedding_service import Embedder, EmbeddingError
from app.services.ingestion.base import DocumentLoader, LoaderError
from app.services.ingestion.file_loader import FileLoader
from app.services.ingestion.web_loader import WebLoader
from app.services.ingestion.wikipedia_loader import LICENSE as WIKI_LICENSE
from app.services.ingestion.wikipedia_loader import WikipediaLoader
from app.services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)

INTERNET_DISABLED = "La descarga desde internet está desactivada (INGESTION_ALLOW_INTERNET=false)."


class IngestionError(RuntimeError):
    pass


class IngestionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        uploads_dir: Path,
        allow_internet: bool = True,
    ) -> None:
        self._factory = session_factory
        self._uploads = uploads_dir
        self._allow_internet = allow_internet

    # ---------- Encolar (lo usa la API) ----------

    async def enqueue_file(
        self, filename: str, data: bytes, *, owner_user_id: int, personal: bool
    ) -> IngestionJob:
        self._uploads.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name
        stored = self._uploads / f"{uuid.uuid4().hex}_{safe_name}"
        stored.write_bytes(data)
        name = "Mis documentos" if personal else "Documentos subidos"
        return await self._enqueue(
            "file",
            name,
            {"type": "file", "path": str(stored), "filename": safe_name},
            owner_user_id=owner_user_id if personal else None,
            personal=personal,
        )

    async def enqueue_web(self, url: str, max_pages: int) -> IngestionJob:
        self._require_internet()
        domain = httpx.URL(url).host or url
        return await self._enqueue(
            "web",
            f"Web: {domain}",
            {"type": "web", "url": url, "max_pages": max_pages},
            base_uri=url,
        )

    async def enqueue_wikipedia(
        self, titles: list[str], category: str | None, limit: int, language: str = "es"
    ) -> IngestionJob:
        self._require_internet()
        return await self._enqueue(
            "wikipedia",
            f"Wikipedia ({language})",
            {
                "type": "wikipedia",
                "titles": titles,
                "category": category,
                "limit": limit,
                "language": language,
            },
            base_uri=f"https://{language}.wikipedia.org",
            license=WIKI_LICENSE,
        )

    def _require_internet(self) -> None:
        if not self._allow_internet:
            raise IngestionError(INTERNET_DISABLED)

    async def _enqueue(
        self,
        kind: str,
        name: str,
        params: dict[str, Any],
        *,
        owner_user_id: int | None = None,
        personal: bool = False,
        base_uri: str | None = None,
        license: str | None = None,
    ) -> IngestionJob:
        async with self._factory() as session:
            # KnowledgeService sólo se usa aquí para crear la fuente: no necesita embeddings.
            source = await KnowledgeService(session, embedder=None).get_or_create_source(  # type: ignore[arg-type]
                kind,
                name,
                base_uri=base_uri,
                license=license,
                owner_user_id=owner_user_id,
                is_personal=personal,
            )
            job = IngestionJob(source_id=source.id, params=params)
            session.add(job)
            await session.commit()
            logger.info("tarea en cola", extra={"job_id": job.id, "type": params["type"]})
            return job

    # ---------- Ejecutar (lo usa el worker) ----------

    async def process(self, job_id: int, embedder: Embedder, http: httpx.AsyncClient) -> None:
        async with self._factory() as session:
            job = await session.get(IngestionJob, job_id)
            source = await session.get(Source, job.source_id) if job else None
        if job is None or source is None:
            return
        try:
            loader = self._loader_for(job.params, http)
            await self._run(job_id, source, loader, embedder)
        except (LoaderError, IngestionError, EmbeddingError) as exc:
            await self._finish(job_id, "failed", str(exc))
            logger.warning("tarea fallida", extra={"job_id": job_id, "error": str(exc)})
            return
        except Exception as exc:
            await self._finish(job_id, "failed", f"Error inesperado: {exc}")
            logger.exception("tarea con error inesperado", extra={"job_id": job_id})
            return
        finally:
            self._cleanup_upload(job.params)

    def _loader_for(self, params: dict[str, Any], http: httpx.AsyncClient) -> DocumentLoader:
        kind = params.get("type")
        if kind == "file":
            return FileLoader(params["filename"], Path(params["path"]).read_bytes())
        self._require_internet()
        if kind == "web":
            return WebLoader(http, params["url"], max_pages=int(params.get("max_pages", 1)))
        if kind == "wikipedia":
            return WikipediaLoader(
                http,
                titles=params.get("titles") or [],
                category=params.get("category"),
                limit=int(params.get("limit", 50)),
                language=params.get("language", "es"),
            )
        raise IngestionError(f"Tipo de tarea desconocido: {kind}")

    async def _run(
        self, job_id: int, source: Source, loader: DocumentLoader, embedder: Embedder
    ) -> None:
        done = 0
        errors: list[str] = []
        async for raw in loader.load():
            async with self._factory() as session:
                job = await session.get(IngestionJob, job_id)
                if job.status == "cancelled":
                    logger.info("tarea cancelada", extra={"job_id": job_id})
                    return
                service = KnowledgeService(session, embedder)
                source_here = await session.get(Source, source.id)
                try:
                    await service.add_text(
                        source_here,
                        raw.title,
                        raw.text,
                        uri=raw.uri,
                        mime_type=raw.mime_type,
                        language=raw.language,
                    )
                except EmbeddingError:
                    raise
                except Exception as exc:
                    await session.rollback()
                    errors.append(f"{raw.title}: {exc}")
                    logger.warning(
                        "documento omitido", extra={"title": raw.title, "error": str(exc)}
                    )
                    job = await session.get(IngestionJob, job_id)
                done += 1
                job.docs_done = done
                job.docs_total = max(job.docs_total, done)
                if errors:
                    job.error_message = f"{len(errors)} con error. Último: {errors[-1]}"[:1000]
                await session.commit()
        await self._finish(job_id, "done", None)

    async def _finish(self, job_id: int, status: str, error: str | None) -> None:
        async with self._factory() as session:
            job = await session.get(IngestionJob, job_id)
            if job is None or job.status == "cancelled":
                return
            job.status = status
            job.finished_at = datetime.now(UTC)
            if error:
                job.error_message = error[:1000]
            await session.commit()

    @staticmethod
    def _cleanup_upload(params: dict[str, Any]) -> None:
        """El archivo subido ya está en la base: se borra la copia temporal."""
        if params.get("type") == "file":
            Path(params["path"]).unlink(missing_ok=True)

    async def cancel(self, job_id: int) -> bool:
        async with self._factory() as session:
            job = await session.get(IngestionJob, job_id)
            if job is None or job.status not in ("queued", "running"):
                return False
            job.status = "cancelled"
            job.finished_at = datetime.now(UTC)
            await session.commit()
            return True
