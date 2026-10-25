"""Búsqueda de fragmentos de conocimiento: por significado y por palabras clave.

En la Etapa 5, `RetrievalService` combina ambas búsquedas (híbrida).
"""

from dataclasses import dataclass

from sqlalchemy import ColumnElement, false, func, or_, select

from app.models import Chunk, Document, Source
from app.repositories.base_repository import BaseRepository


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float  # más alto = más relevante


def _visible_to(owner_user_id: int | None) -> ColumnElement[bool]:
    """Los documentos personales sólo los ve su dueño."""
    if owner_user_id is None:
        return Source.is_personal.is_(false())
    return or_(Source.is_personal.is_(false()), Source.owner_user_id == owner_user_id)


class ChunkRepository(BaseRepository[Chunk]):
    model = Chunk

    async def nearest(
        self, embedding: list[float], k: int = 5, owner_user_id: int | None = None
    ) -> list[ScoredChunk]:
        """Los k fragmentos más parecidos en significado (similitud coseno)."""
        distance = Chunk.embedding.cosine_distance(embedding)
        stmt = (
            select(Chunk, distance.label("distance"))
            .join(Document)
            .join(Source)
            .where(Chunk.embedding.is_not(None), _visible_to(owner_user_id))
            .order_by(distance)
            .limit(k)
        )
        rows = (await self.session.execute(stmt)).all()
        return [ScoredChunk(chunk=row.Chunk, score=1.0 - row.distance) for row in rows]

    async def full_text(
        self, query: str, k: int = 5, owner_user_id: int | None = None
    ) -> list[ScoredChunk]:
        """Los k fragmentos que mejor coinciden con las palabras de la consulta."""
        ts_query = func.websearch_to_tsquery("spanish", query)
        rank = func.ts_rank(Chunk.tsv, ts_query)
        stmt = (
            select(Chunk, rank.label("rank"))
            .join(Document)
            .join(Source)
            .where(Chunk.tsv.bool_op("@@")(ts_query), _visible_to(owner_user_id))
            .order_by(rank.desc())
            .limit(k)
        )
        rows = (await self.session.execute(stmt)).all()
        return [ScoredChunk(chunk=row.Chunk, score=float(row.rank)) for row in rows]
