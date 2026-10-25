"""Búsqueda híbrida: encuentra los fragmentos que mejor responden una pregunta.

1. Búsqueda por **significado** (vectores, pgvector): entiende sinónimos y paráfrasis
   ("¿dónde guarda los datos?" encuentra "PostgreSQL almacena…").
2. Búsqueda por **palabras** (texto completo de PostgreSQL): no falla con nombres
   propios, números y siglas ("5434", "HNSW", "Piper").
3. **Reciprocal Rank Fusion (RRF):** combina las dos listas por posición, no por
   puntaje, porque los puntajes de cada búsqueda no son comparables entre sí:

       puntaje(fragmento) = Σ 1 / (60 + posición en cada lista)

4. **Filtro de relevancia:** se descartan fragmentos poco parecidos a la pregunta,
   para no darle al modelo contexto que lo confunda (por ejemplo, ante un "hola").
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import ChunkRepository, ScoredChunk
from app.services.embedding_service import Embedder

RRF_K = 60


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    content: str
    title: str | None
    section: str | None
    uri: str | None
    score: float  # puntaje RRF
    similarity: float | None


@dataclass(frozen=True)
class RetrievalSettings:
    top_k: int = 3
    candidates: int = 20
    # Similitud mínima para aceptar un fragmento sólo por significado.
    min_similarity: float = 0.5
    # Un fragmento que también coincide por palabras se acepta con algo menos.
    min_similarity_with_keywords: float = 0.42


def reciprocal_rank_fusion(*rankings: list[ScoredChunk]) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for position, item in enumerate(ranking, start=1):
            scores[item.chunk.id] = scores.get(item.chunk.id, 0.0) + 1.0 / (RRF_K + position)
    return scores


class RetrievalService:
    def __init__(
        self,
        session: AsyncSession,
        embedder: Embedder,
        settings: RetrievalSettings | None = None,
    ) -> None:
        self._repo = ChunkRepository(session)
        self._embedder = embedder
        self._settings = settings or RetrievalSettings()

    async def search(self, query: str, owner_user_id: int | None = None) -> list[RetrievedChunk]:
        cfg = self._settings
        embedding = (await self._embedder.embed([query]))[0]

        by_meaning = await self._repo.nearest(
            embedding, k=cfg.candidates, owner_user_id=owner_user_id
        )
        by_words = await self._repo.full_text(
            query, k=cfg.candidates, owner_user_id=owner_user_id, match="any", embedding=embedding
        )

        words_ids = {item.chunk.id for item in by_words}
        candidates = {item.chunk.id: item for item in [*by_words, *by_meaning]}

        def relevant(item: ScoredChunk) -> bool:
            similarity = item.similarity or 0.0
            if item.chunk.id in words_ids:
                return similarity >= cfg.min_similarity_with_keywords
            return similarity >= cfg.min_similarity

        fused = reciprocal_rank_fusion(by_meaning, by_words)
        ranked = sorted(
            (cid for cid in fused if relevant(candidates[cid])),
            key=lambda cid: fused[cid],
            reverse=True,
        )[: cfg.top_k]

        return [self._to_result(candidates[cid], fused[cid]) for cid in ranked]

    @staticmethod
    def _to_result(item: ScoredChunk, score: float) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=item.chunk.id,
            content=item.chunk.content,
            title=item.title,
            section=(item.chunk.metadata_ or {}).get("section"),
            uri=item.uri,
            score=round(score, 5),
            similarity=None if item.similarity is None else round(item.similarity, 4),
        )
