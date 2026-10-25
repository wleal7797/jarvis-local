"""Agrega conocimiento a JARVIS: texto → fragmentos → vectores → PostgreSQL.

Es el núcleo de la ingesta. En la Etapa 6 los cargadores (archivos, web, Wikipedia)
y el worker en segundo plano usan este mismo servicio.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document, Source
from app.services.chunker import DEFAULT_MAX_TOKENS, chunk_text
from app.services.embedding_service import Embedder, EmbeddingError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexResult:
    document: Document
    chunks: int
    created: bool  # False si el documento ya existía (mismo contenido)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


class KnowledgeService:
    def __init__(self, session: AsyncSession, embedder: Embedder) -> None:
        self._session = session
        self._embedder = embedder

    async def get_or_create_source(
        self,
        kind: str,
        name: str,
        *,
        base_uri: str | None = None,
        license: str | None = None,
        owner_user_id: int | None = None,
        is_personal: bool = False,
    ) -> Source:
        source = await self._session.scalar(
            select(Source).where(
                Source.kind == kind,
                Source.name == name,
                Source.owner_user_id.is_(None)
                if owner_user_id is None
                else Source.owner_user_id == owner_user_id,
            )
        )
        if source is None:
            source = Source(
                kind=kind,
                name=name,
                base_uri=base_uri,
                license=license,
                owner_user_id=owner_user_id,
                is_personal=is_personal,
            )
            self._session.add(source)
            await self._session.flush()
        return source

    async def add_text(
        self,
        source: Source,
        title: str,
        text: str,
        *,
        uri: str | None = None,
        mime_type: str = "text/markdown",
        language: str = "es",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> IndexResult:
        digest = content_hash(text)
        existing = await self._session.scalar(
            select(Document).where(Document.content_hash == digest)
        )
        if existing is not None:
            return IndexResult(document=existing, chunks=0, created=False)

        # Mismo archivo (misma uri) con contenido nuevo: se reemplaza la versión anterior.
        if uri is not None:
            outdated = await self._session.scalars(
                select(Document).where(Document.source_id == source.id, Document.uri == uri)
            )
            for old_document in outdated.all():
                await self._session.delete(old_document)
            await self._session.flush()

        document = Document(
            source=source,
            title=title,
            uri=uri,
            mime_type=mime_type,
            language=language,
            content_hash=digest,
            status="processing",
        )
        self._session.add(document)
        await self._session.flush()

        pieces = chunk_text(text, title, max_tokens=max_tokens)
        try:
            vectors = await self._embedder.embed([p.text for p in pieces])
        except EmbeddingError as exc:
            document.status = "error"
            document.error_message = str(exc)
            await self._session.flush()
            raise

        self._session.add_all(
            Chunk(
                document_id=document.id,
                chunk_index=i,
                content=piece.text,
                token_count=piece.token_count,
                embedding=vector,
                metadata_={"section": piece.section},
            )
            for i, (piece, vector) in enumerate(zip(pieces, vectors, strict=True))
        )
        document.status = "indexed"
        document.indexed_at = datetime.now(UTC)
        await self._session.flush()
        logger.info(
            "documento indexado",
            extra={"document_id": document.id, "title": title, "chunks": len(pieces)},
        )
        return IndexResult(document=document, chunks=len(pieces), created=True)
