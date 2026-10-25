"""Búsqueda de fragmentos de conocimiento: por significado y por palabras clave.

`RetrievalService` combina ambas búsquedas (búsqueda híbrida).
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, Text, cast, false, func, literal, or_, select

from app.models import Chunk, Document, Source
from app.repositories.base_repository import BaseRepository

Match = Literal["all", "any"]


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float  # más alto = más relevante (el significado depende de la búsqueda)
    title: str | None = None
    uri: str | None = None
    similarity: float | None = None  # similitud coseno con la consulta, si se calculó


def _visible_to(owner_user_id: int | None) -> ColumnElement[bool]:
    """Los documentos personales sólo los ve su dueño."""
    if owner_user_id is None:
        return Source.is_personal.is_(false())
    return or_(Source.is_personal.is_(false()), Source.owner_user_id == owner_user_id)


def _ts_query(query: str, match: Match) -> ColumnElement:
    """`all`: deben aparecer todas las palabras. `any`: basta con una (más permisivo)."""
    if match == "all":
        return func.websearch_to_tsquery("spanish", query)
    # plainto_tsquery une con '&'; se cambia por '|' para aceptar cualquier palabra.
    anded = cast(func.plainto_tsquery("spanish", query), Text)
    return func.to_tsquery("spanish", func.replace(anded, "&", "|"))


class ChunkRepository(BaseRepository[Chunk]):
    model = Chunk

    async def nearest(
        self,
        embedding: list[float],
        k: int = 5,
        owner_user_id: int | None = None,
        min_similarity: float | None = None,
    ) -> list[ScoredChunk]:
        """Los k fragmentos más parecidos en significado (similitud coseno)."""
        distance = Chunk.embedding.cosine_distance(embedding)
        stmt = (
            select(Chunk, Document.title, Document.uri, distance.label("distance"))
            .join(Document)
            .join(Source)
            .where(Chunk.embedding.is_not(None), _visible_to(owner_user_id))
            .order_by(distance)
            .limit(k)
        )
        if min_similarity is not None:
            stmt = stmt.where(distance <= 1 - min_similarity)
        rows = (await self.session.execute(stmt)).all()
        return [
            ScoredChunk(
                chunk=row.Chunk,
                score=1.0 - row.distance,
                title=row.title,
                uri=row.uri,
                similarity=1.0 - row.distance,
            )
            for row in rows
        ]

    async def full_text(
        self,
        query: str,
        k: int = 5,
        owner_user_id: int | None = None,
        match: Match = "all",
        embedding: list[float] | None = None,
    ) -> list[ScoredChunk]:
        """Los k fragmentos que mejor coinciden con las palabras de la consulta.

        Si se pasa `embedding`, también calcula la similitud de cada resultado.
        """
        ts_query = _ts_query(query, match)
        rank = func.ts_rank_cd(Chunk.tsv, ts_query)
        similarity = (
            (1 - Chunk.embedding.cosine_distance(embedding)) if embedding else literal(None)
        )
        stmt = (
            select(
                Chunk,
                Document.title,
                Document.uri,
                rank.label("rank"),
                similarity.label("similarity"),
            )
            .join(Document)
            .join(Source)
            .where(Chunk.tsv.bool_op("@@")(ts_query), _visible_to(owner_user_id))
            .order_by(rank.desc())
            .limit(k)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            ScoredChunk(
                chunk=row.Chunk,
                score=float(row.rank),
                title=row.title,
                uri=row.uri,
                similarity=None if row.similarity is None else float(row.similarity),
            )
            for row in rows
        ]
